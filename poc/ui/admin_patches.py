"""Admin page to review reflection patches. Approve appends, reject removes, reversibly."""
import threading
import time

import streamlit as st

from teaf import reflection, store

# Background consolidation so BOTH agents can run at once: each click starts a daemon thread.
_CONSOLIDATION_JOBS: dict[int, threading.Thread] = {}
_CONSOLIDATION_RESULTS: dict[int, str] = {}


def _consolidation_running(agent_id: int) -> bool:
    job = _CONSOLIDATION_JOBS.get(agent_id)
    if job is None:
        return False
    if job.is_alive():
        return True
    _CONSOLIDATION_JOBS.pop(agent_id, None)
    return False


def _start_consolidation(agent_id: int) -> None:
    if _consolidation_running(agent_id):
        return

    def _worker() -> None:
        try:
            _CONSOLIDATION_RESULTS[agent_id] = reflection.consolidate_pending_patches(agent_id)["message"]
        except Exception as e:  # never crash the worker thread
            _CONSOLIDATION_RESULTS[agent_id] = f"Consolidation failed: {e}"
        finally:
            _CONSOLIDATION_JOBS.pop(agent_id, None)

    job = threading.Thread(target=_worker, daemon=True)
    _CONSOLIDATION_JOBS[agent_id] = job
    job.start()


def _approve(p) -> None:
    addition = reflection.extract_suggested_addition(p["content"])
    if addition:
        store.append_to_system_prompt(p["agent_id"], addition)  # idempotent
    store.set_patch_status(p["id"], "approved")


def _reject(p) -> None:
    addition = reflection.extract_suggested_addition(p["content"])
    if addition:
        store.remove_from_system_prompt(p["agent_id"], addition)  # reverse the append
    store.set_patch_status(p["id"], "rejected")


def _agent_name(agent_id: int) -> str:
    agent = store.get_agent(agent_id)
    return agent["name"] if agent else f"agent {agent_id}"


def _consolidation_controls(pending) -> bool:
    """Per-agent 'Consolidate pending' buttons + a running line per active job.

    Both buttons show when both agents are eligible; clicking one starts it in the
    background and shows a running line, so a second can be started while the first
    is still going. Returns True while any consolidation is still running."""
    counts: dict[int, int] = {}
    for p in pending:
        counts[p["agent_id"]] = counts.get(p["agent_id"], 0) + 1
    # Show a button for any agent with 2+ pending OR one currently consolidating.
    agent_ids = sorted({aid for aid, n in counts.items() if n >= 2} | set(_CONSOLIDATION_JOBS.keys()))
    if not agent_ids:
        return False

    st.caption(
        "Repeated reflections in one conversation can leave many near-duplicate patches. "
        "Consolidate merges an agent's pending patches into one (using the configurable "
        "prompt in Settings → Interaction triggers); the originals are kept for audit."
    )
    cols = st.columns(len(agent_ids))
    for col, agent_id in zip(cols, agent_ids):
        n = counts.get(agent_id, 0)
        running = _consolidation_running(agent_id)
        if col.button(
            f"🧩 Consolidate {n} pending patches for {_agent_name(agent_id)}",
            key=f"consolidate_{agent_id}", type="primary",
            use_container_width=True, disabled=running or n < 2,
        ):
            _start_consolidation(agent_id)
            st.rerun()

    # One running line per active job, until it finishes.
    any_running = False
    for agent_id in sorted(_CONSOLIDATION_JOBS.keys()):
        any_running = True
        st.info(f"Consolidating pending patches for {_agent_name(agent_id)}…", icon="⏳")
    return any_running


def _render_card(p, *, can_approve: bool, can_reject: bool) -> None:
    agent = store.get_agent(p["agent_id"])
    addition = reflection.extract_suggested_addition(p["content"])
    target = agent["name"] if agent else "Unknown agent"
    with st.container(border=True):
        st.markdown(f"**Patch #{p['id']}**")
        st.info(f"Target agent: {target}")
        st.caption(f"Session {p['session_id']} · {p['created_at']}")
        with st.expander("View full patch"):
            st.markdown(p["content"])
        if addition:
            st.markdown("**System-prompt addition:**")
            st.code(addition, language="markdown")
        else:
            st.warning("No 'Suggested system-prompt addition' section found — "
                       "approving records the decision but appends nothing.")
        cols = st.columns(2)
        if can_approve and cols[0].button("✅ Approve", key=f"approve_{p['id']}", type="primary"):
            _approve(p)
            st.rerun()
        if can_reject and cols[1].button("❌ Reject", key=f"reject_{p['id']}"):
            _reject(p)
            st.rerun()


def render() -> None:
    st.title("📝 Tacit Externalisation")
    # Surface any finished background consolidation(s).
    for agent_id in list(_CONSOLIDATION_RESULTS.keys()):
        if agent_id not in _CONSOLIDATION_JOBS:
            st.toast(_CONSOLIDATION_RESULTS.pop(agent_id), icon="✅")
    notice = st.session_state.pop("patches_notice", None)
    if notice:
        st.toast(notice, icon="✅")
    st.caption(
        "Self-reflection proposes prompt additions; the "
        "human disposes, reversibly. Approving appends the suggested text to the agent's "
        "system prompt; rejecting removes it. Nothing is ever auto-merged."
    )

    pending = store.list_patches(status="pending")
    approved = store.list_patches(status="approved")
    rejected = store.list_patches(status="rejected")
    tabs = st.tabs([f"Pending ({len(pending)})", f"Approved ({len(approved)})", f"Rejected ({len(rejected)})"])

    consolidating = False
    with tabs[0]:
        if not pending:
            st.info("No pending patches. They appear after self-reflection runs "
                    "(every N turns or at session end — see Interaction triggers).")
        consolidating = _consolidation_controls(pending)
        for p in pending:
            _render_card(p, can_approve=True, can_reject=True)

    with tabs[1]:
        if not approved:
            st.info("No approved patches yet.")
        for p in approved:
            _render_card(p, can_approve=False, can_reject=True)  # can revoke

    with tabs[2]:
        if not rejected:
            st.info("No rejected patches yet.")
        for p in rejected:
            _render_card(p, can_approve=True, can_reject=False)  # can re-accept

    # Keep refreshing while any background consolidation runs so the running line
    # clears and the new consolidated patch appears as soon as it completes.
    if consolidating:
        time.sleep(1)
        st.rerun()
