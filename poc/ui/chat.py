"""Chat page"""
import hashlib
import threading
import time

import streamlit as st

import config
from teaf import orchestration, store
from teaf.explicit_channels import anomaly, rag

_CHAT_JOBS: dict[int, threading.Thread] = {}
_CHAT_PHASES: dict[int, str] = {}

_MODE_BADGE = {
    config.MODE_COACHING: "Coaching",
    config.MODE_FACILITATION: "Facilitation",
    config.MODE_CONSULTING: "Consulting",
}
_FRIENDLY_COLLECTION = {
    config.COLLECTION_DOMAIN: "EA governance documents",
    config.COLLECTION_COACHING: "Coaching instructions and frameworks",
}


def _friendly(collection: str) -> str:
    return _FRIENDLY_COLLECTION.get(collection, collection.replace("_", " ").title())


def _flagged_table_html(records) -> str:
    """Token-styled HTML table (themes in both modes, unlike the canvas dataframe)."""
    import html as _html

    def cell(v):
        return _html.escape("" if v is None else str(v))

    head = "<tr><th>app_id</th><th>reason</th><th>source</th><th>score</th></tr>"
    rows = "".join(
        f"<tr><td>{cell(r['app_id'])}</td><td>{cell(r['reason'])}</td>"
        f"<td>{cell(r['source'])}</td><td>{cell(r['score'])}</td></tr>"
        for r in records
    )
    return (
        "<div style='max-height:320px;overflow:auto'>"
        f"<table class='teaf-table'><thead>{head}</thead><tbody>{rows}</tbody></table></div>"
    )


def _upload_sig(name: str, data: bytes) -> str:
    return f"{name}:{hashlib.sha256(data).hexdigest()}"


def _ensure_session() -> dict:
    s = store.get_active_session()
    if s is None:
        store.create_session()
        s = store.get_active_session()
    return s


# --- top control panel --------------------------------------------------------
def _render_warnings() -> None:
    # Keyed container so CSS forces these into red boxes in both themes; a model is required.
    with st.container(key="model_warnings"):
        if store.get_agent_by_role(config.ROLE_COACHING)["model_id"] is None:
            st.warning(
                "The Coaching Agent has no model assigned. Register one under **Settings → "
                "Models**, then assign it under **Settings → Agents**.",
                icon="ℹ️",
            )
        if store.get_agent_by_role(config.ROLE_DOMAIN)["model_id"] is None:
            st.warning(
                "The Domain Agent has no model assigned yet — judgement-driven domain "
                "lookups will degrade gracefully until you assign one (Settings → Agents).",
                icon="ℹ️",
            )


def _render_dataset_row(d: dict) -> None:
    """One portfolio-CSV row: name + download + a confirmed Remove action."""
    name = d["name"]
    c1, c2, c3 = st.columns([4, 1, 1])
    c1.write(f"📄 `{name}` — {d['rows']} rows")
    c2.download_button(
        "Download", data=anomaly.read_dataset(name), file_name=name,
        mime="text/csv", key=f"dl_ds_{name}",
    )
    confirm_key = f"ds_confirm_rm_{name}"
    if c3.button("Remove", key=f"rm_ds_{name}"):
        st.session_state[confirm_key] = True
        st.rerun()
    if not st.session_state.get(confirm_key):
        return
    st.warning(f"Remove `{name}` from the data scope? This cannot be undone.")
    cc1, cc2 = st.columns(2)
    if cc1.button("Confirm remove", key=f"ds_ok_{name}", type="primary"):
        anomaly.remove_dataset(name)
        anomaly.clear_cache()
        st.session_state.pop(confirm_key, None)
        st.rerun()
    if cc2.button("Cancel", key=f"ds_no_{name}"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


def _render_data_scope() -> None:
    st.markdown("**Current data scope**")
    datasets = anomaly.list_datasets()
    if not datasets:
        st.caption("No datasets yet. The bundled default portfolio loads on first detection.")
    for d in datasets:
        _render_dataset_row(d)

    # Rotate the uploader key on a successful add so the chip clears automatically.
    ukey = f"anom_csv_{st.session_state.get('anom_csv_ver', 0)}"
    up = st.file_uploader("Upload a portfolio CSV", type=["csv"], key=ukey)
    if up is not None:
        saved = anomaly.add_dataset(up.name, up.getvalue())
        anomaly.clear_cache()
        st.session_state["anom_csv_ver"] = st.session_state.get("anom_csv_ver", 0) + 1
        st.session_state["anomaly_detection_status"] = (
            f"Added `{saved}` to the current data scope. Run detection to refresh the anomaly results."
        )
        st.rerun()

    run_col, _spacer = st.columns([1.4, 3.6])
    if run_col.button("Run detection", type="primary", use_container_width=True):
        _run_detection()
        st.rerun()


def _run_detection() -> None:
    """Run the hybrid detector with a visible status indicator and store the result."""
    try:
        with st.status("Running anomaly detection...", expanded=True) as status:
            status.markdown("- Reading the current CSV data scope")
            status.markdown("- Running rule-based data-quality checks")
            status.markdown("- Running statistical outlier detection")
            payload = anomaly.get_payload(refresh=True)
            s = payload["summary"]
            mapping = s.get("field_mapping") or {}
            skipped = s.get("skipped_missing_fields") or []
            status.markdown(
                f"- Completed: {s['total']} applications, {s['rule_flags']} rule flags, "
                f"{s['ml_flags']} statistical outliers"
            )
            status.markdown("- Governance task queue synchronised without model calls")
            mapped_items = [(k, v) for k, v in mapping.items() if v]
            if mapped_items:
                status.markdown(
                    "- Field mapping: " + ", ".join(f"`{k}` ← `{v}`" for k, v in mapped_items)
                )
            if skipped:
                status.markdown(
                    "- Skipped rules for missing fields: " + ", ".join(f"`{x}`" for x in skipped)
                )
            status.update(label="Anomaly detection complete", state="complete")
        st.session_state["anomaly_detection_status"] = (
            f"Detection complete: {s['total']} applications, {s['rule_flags']} rule flags, "
            f"{s['ml_flags']} statistical outliers."
        )
    except Exception as e:
        st.session_state["anomaly_detection_status"] = f"Detection failed: {e}"
        st.error(f"Detection failed: {e}")


def _is_turn_running(session_id: int) -> bool:
    job = _CHAT_JOBS.get(session_id)
    if job is None:
        return False
    if job.is_alive():
        return True
    _CHAT_JOBS.pop(session_id, None)
    return False


def _run_turn_worker(session_id: int, text: str, forced_mode=None) -> None:
    def on_phase(label, detail=None):
        _CHAT_PHASES[session_id] = str(label)

    try:
        orchestration.handle_user_turn(session_id, text, forced_mode=forced_mode, on_phase=on_phase)
    finally:
        _CHAT_JOBS.pop(session_id, None)
        _CHAT_PHASES.pop(session_id, None)


def _start_turn(session_id: int, text: str, forced_mode=None) -> bool:
    if _is_turn_running(session_id):
        return False
    job = threading.Thread(
        target=_run_turn_worker, args=(session_id, text, forced_mode), daemon=True
    )
    _CHAT_JOBS[session_id] = job
    job.start()
    return True


def _render_anomaly_panel() -> None:
    with st.expander("🧪 Anomaly Detection · Dynamic Explicit Channel"):
        _render_data_scope()
        detection_status = st.session_state.get("anomaly_detection_status")
        if detection_status:
            if str(detection_status).startswith("Detection failed"):
                st.error(detection_status)
            else:
                # Plain line (not st.success) so it isn't a box inside the expander box.
                st.markdown(f"✅ {detection_status}")

        payload = anomaly.current_payload()
        if not payload:
            # Plain line (not st.info) so it isn't a box inside the expander box.
            st.markdown(
                "ℹ️ Add/keep CSVs above, then click **Run detection** to see the flagged records."
            )
            return
        s = payload["summary"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Applications", s["total"])
        c2.metric("Rule flags", s["rule_flags"])
        c3.metric("ML flags", s["ml_flags"])
        st.markdown(_flagged_table_html(payload["flagged_records"]), unsafe_allow_html=True)


def _render_kb_doc_row(collection: str, doc: str, owner_label: str) -> None:
    """One document row: name + download + a confirmed Remove action."""
    c1, c2, c3 = st.columns([4, 1, 1])
    c1.write(f"📄 `{doc}`")
    try:
        text = rag.read_document(collection, doc)
    except Exception:
        text = ""
    c2.download_button(
        "Download", data=text.encode("utf-8"), file_name=doc, mime="text/plain",
        key=f"dl_rag_{collection}_{doc}",
    )
    confirm_key = f"rag_confirm_rm_{collection}_{doc}"
    if c3.button("Remove", key=f"rm_rag_{collection}_{doc}"):
        st.session_state[confirm_key] = True
        st.rerun()
    if not st.session_state.get(confirm_key):
        return
    st.warning(
        f"Remove `{doc}` from {owner_label} RAG? This deletes its chunks from the "
        "vector store and cannot be undone."
    )
    cc1, cc2 = st.columns(2)
    if cc1.button("Confirm remove", key=f"rm_ok_{collection}_{doc}", type="primary"):
        rag.remove_document(collection, doc)
        st.session_state.pop(confirm_key, None)
        st.session_state["rag_notice"] = f"Removed `{doc}` from {owner_label} RAG."
        st.rerun()
    if cc2.button("Cancel", key=f"rm_no_{collection}_{doc}"):
        st.session_state.pop(confirm_key, None)
        st.rerun()


def _handle_rag_upload(collection: str, owner_label: str, up) -> None:
    data = up.getvalue()
    sig = _upload_sig(f"{collection}:{up.name}", data)
    # Same file already attempted and not added (skipped/failed) → keep it staged.
    if st.session_state.get(f"rag_last_attempt_{collection}") == sig:
        st.caption(f"`{up.name}` is staged but was not added — replace or remove it to retry.")
        return
    with st.status(f"Indexing upload into {owner_label} RAG...", expanded=True) as status:
        status.markdown("- Reading uploaded document")
        status.markdown("- Chunking and embedding content")
        try:
            result = rag.ingest_upload(collection, up.name, data)
        except Exception as e:
            status.update(label="Upload failed", state="error")
            st.session_state[f"rag_last_attempt_{collection}"] = sig  # don't reprocess on every rerun
            st.error(f"Could not ingest `{up.name}`: {e}")  # keep the staged file so the user can retry
            return
        status.update(label=f"{owner_label} RAG updated", state="complete")

    if result["skipped"]:
        st.session_state[f"rag_last_attempt_{collection}"] = sig  # keep the file; show why it was skipped
        st.warning(f"Skipped `{up.name}`: {result['reason']}")
        return

    # Success → clear the uploader by rotating its key, and toast a transient notice.
    st.session_state[f"up_ver_{collection}"] = st.session_state.get(f"up_ver_{collection}", 0) + 1
    st.session_state["rag_notice"] = f"Added `{up.name}` to {owner_label} RAG ({result['chunks']} chunks)."
    st.rerun()


def _render_kb_collection(collection: str, owner_label: str) -> None:
    st.markdown(f"**{owner_label} RAG - {_friendly(collection)}**")
    try:
        docs = rag.list_available_documents(collection)
    except Exception as e:
        st.error(f"RAG unavailable: {e}")
        return

    if docs:
        st.caption("Documents currently in scope")
        for doc in docs:
            _render_kb_doc_row(collection, doc, owner_label)
    else:
        st.caption("No documents in this scope yet.")

    ver = st.session_state.get(f"up_ver_{collection}", 0)
    up = st.file_uploader(
        f"Upload a .txt / .md / .pdf document to {owner_label} RAG",
        type=["txt", "md", "pdf"],
        key=f"up_{collection}_{ver}",
    )
    if up is not None:
        _handle_rag_upload(collection, owner_label, up)


def _render_kb_panel() -> None:
    with st.expander("📚 RAG · Static Explicit Channel"):
        domain_cols = store.list_agent_rag_by_role(config.ROLE_DOMAIN)
        coaching_cols = store.list_agent_rag_by_role(config.ROLE_COACHING)
        for c in domain_cols:
            _render_kb_collection(c["collection_name"], "Domain Agent")
            st.divider()
        for i, c in enumerate(coaching_cols):
            _render_kb_collection(c["collection_name"], "Coaching Agent")
            if i < len(coaching_cols) - 1:
                st.divider()


def _render_tacit_info_panel() -> None:
    with st.expander("🧠 Prompt Engineering · Externalised Tacit Channel"):
        # Plain line (not st.info) so it doesn't render a box inside the expander box.
        st.markdown(
            "ℹ️ The agent comes with a pre-defined system prompt, and the framework feeds it "
            "additional knowledge over time via tacit externalisation."
        )


def _render_top_panel(session: dict) -> None:
    with st.container(border=True, key="data_sources"):
        row = st.columns([5, 3.4], vertical_alignment="center")
        row[0].markdown("**Data Sources**")
        if row[1].button("End Session & Externalise Tacit Knowledge", type="primary", use_container_width=True):
            # Show the working indicator IN the button's column (the user's focus),
            # not up in the data-sources panel.
            with row[1]:
                with st.spinner("Ending session & externalising tacit knowledge…"):
                    orchestration.end_session(session["id"])
            store.create_session()
            st.rerun()

        _render_warnings()

        _render_kb_panel()
        _render_anomaly_panel()
        _render_tacit_info_panel()


# --- conversation -------------------------------------------------------------
def _render_process_steps(session_id: int, turn: int, messages: list) -> None:
    steps = store.list_process_steps(session_id, turn)
    legacy_domain = next((m for m in messages if m["role"] == "domain"), None)
    system_messages = [m for m in messages if m["role"] == "system"]

    with st.expander("🔎 Internal process steps"):
        st.caption(
            "Recorded application events and exchanged evidence for this response. "
            "This is an operational trace, not the model's private chain of thought."
        )
        if steps:
            for index, step in enumerate(steps, start=1):
                status = step["status"]
                suffix = "" if status == "completed" else f" ({status})"
                st.markdown(f"**{index}. {step['title']}{suffix}**")
                if step["detail"]:
                    st.markdown(step["detail"])
                if index < len(steps):
                    st.divider()
        else:
            st.info(
                "This response predates process tracing. Only information already stored "
                "with the conversation can be shown."
            )
            if legacy_domain is not None:
                st.markdown("**Available Domain Agent analysis**")
                st.text(legacy_domain["content"])

        if system_messages:
            st.divider()
            st.markdown("**Recorded system notices**")
            for message in system_messages:
                st.caption(message["content"])


def _render_history(session_id: int) -> None:
    messages_by_turn: dict[int, list] = {}
    for message in store.list_messages(session_id):
        messages_by_turn.setdefault(message["turn"], []).append(message)

    for turn, messages in messages_by_turn.items():
        for message in messages:
            if message["role"] != "user":
                continue
            with st.chat_message("user"):
                st.markdown(
                    "<span class='teaf-chat-sentinel teaf-user-message'></span>",
                    unsafe_allow_html=True,
                )
                st.markdown(message["content"])

        coaching = next((m for m in messages if m["role"] == "coaching"), None)
        if coaching is None:
            continue
        badge = _MODE_BADGE.get(coaching["mode"], "")
        with st.chat_message("assistant"):
            st.markdown(
                "<span class='teaf-chat-sentinel teaf-agent-message'></span>",
                unsafe_allow_html=True,
            )
            if badge:
                st.markdown(
                    f"<span class='teaf-chat-badge teaf-chat-badge-{coaching['mode']}'>{badge}</span>",
                    unsafe_allow_html=True,
                )
            st.markdown(coaching["content"])
            _render_process_steps(session_id, turn, messages)


def render() -> None:
    st.title("Coaching conversation")
    notice = st.session_state.pop("rag_notice", None)
    if notice:
        st.toast(notice, icon="📚")
    session = _ensure_session()
    _render_top_panel(session)

    st.markdown("<div class='teaf-chat-section-spacer'></div>", unsafe_allow_html=True)
    st.markdown(
        f"<h3 class='teaf-conversation-heading'>💬 Conversation"
        f"<span class='teaf-session-tag'>session #{session['id']}</span></h3>",
        unsafe_allow_html=True,
    )

    has_messages = store.max_turn(session["id"]) > 0
    busy = _is_turn_running(session["id"])

    if has_messages or busy:
        # History scrolls inside its own fixed-height region so the header above
        # (title + Data Sources) stays put when reading long conversations. The
        # height adapts to the viewport via CSS; autoscroll jumps to the newest turn.
        with st.container(height=760, autoscroll=True, key="chat_history"):
            _render_history(session["id"])
            # Interim / thinking / "consulting domain agent" status renders INSIDE the
            # conversation, as the last item, so the user sees it in context.
            if busy:
                phase = _CHAT_PHASES.get(session["id"], "Agent is responding...")
                with st.status(phase, expanded=True):
                    st.markdown(f"- {phase}")
    elif not has_messages:
        # Empty conversation: offer starter chips. They vanish once a turn starts.
        _render_starter_chips(session)
    prompt = st.chat_input("Talk to your EA governance coach...", disabled=busy)
    if prompt:
        _start_turn(session["id"], prompt)
        st.rerun()
    if busy:
        time.sleep(1)
        st.rerun()


def _render_starter_chips(session: dict) -> None:
    """Suggestion chips shown only when the conversation is empty. Clicking one sends
    its prompt as the user's first message."""
    chips = []
    if anomaly.current_payload() is not None:
        chips.append((
            "anom",
            "Review anomalies",
            "Let's review the anomalies you just detected — which should I prioritise, and why?",
            None,
        ))
    chips.append((
        "gov",
        "Explore EA documents",
        "Start a coaching session about our internal EA governance documents.",
        config.MODE_COACHING,
    ))
    chips.append((
        "tech",
        "Coach a technical issue",
        "I have a technical problem and I'd like you to coach me through how to tackle it.",
        config.MODE_COACHING,
    ))
    chips.append((
        "review",
        "Coach architecture review",
        "Coach me through the architecture review process",
        config.MODE_COACHING,
    ))

    # Keyed container → CSS class `st-key-teaf_starters`, fixed just above the chat input.
    with st.container(key="teaf_starters"):
        st.caption("Not sure where to start? Pick a prompt:")
        cols = st.columns(len(chips))
        for col, (key, label, prompt, mode) in zip(cols, chips):
            if col.button(label, key=f"starter_{key}", use_container_width=True):
                _start_turn(session["id"], prompt, forced_mode=mode)
                st.rerun()
