"""Admin page for the interaction triggers. Only Trigger B is configurable."""
import html

import streamlit as st
import streamlit.components.v1 as components

import config
from teaf import reflection, store


def _reflection_when(every_n: int, at_end: bool) -> str:
    reflect_label = []
    if every_n and every_n > 0:
        reflect_label.append(f"every {every_n} turns")
    if at_end:
        reflect_label.append("at session end")
    return " / ".join(reflect_label) if reflect_label else "disabled"


def _flow_tokens() -> dict[str, str]:
    if bool(st.session_state.get("light_mode", True)):
        return {
            "bg": "#ffffff",
            "border": "#9aa7b8",
            "text": "#151922",
            "muted": "#3f4c5c",
            "primary": "#2563eb",
        }
    return {
        "bg": "#181b20",
        "border": "#3b424d",
        "text": "#f2f4f8",
        "muted": "#b2bac6",
        "primary": "#4f8cff",
    }
"""
This is the SVG diagram on the Interaction triggers page.
"""

def _flow_diagram_html(every_n: int, at_end: bool) -> str:
    reflect_when = html.escape(_reflection_when(every_n, at_end))
    t = _flow_tokens()
    return f"""
    <!doctype html>
    <html>
    <head>
      <style>
        html, body {{
          margin:0; padding:0; background:transparent; color:{t["text"]};
          font-family:Arial, Helvetica, sans-serif;
        }}
        .teaf-flow-diagram {{
          box-sizing:border-box; width:100%; overflow-x:auto; overflow-y:hidden; background:{t["bg"]};
          border:1px solid {t["border"]}; border-radius:8px; padding:8px;
        }}
        svg {{ display:block; width:100%; min-width:1180px; height:330px; color:{t["text"]}; }}
        .teaf-flow-label {{ fill:{t["text"]}; }}
        .teaf-flow-label-muted {{ fill:{t["muted"]}; }}
        .teaf-flow-blue {{ fill:{t["primary"]}; }}
      </style>
    </head>
    <body>
    <div class="teaf-flow-diagram" role="img" aria-label="TEAF interaction trigger flow">
      <svg viewBox="0 0 1480 380" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <marker id="teaf-arrow-main" markerWidth="10" markerHeight="10" refX="9" refY="5"
                  orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L10,5 L0,10 Z" fill="{t["text"]}" />
          </marker>
          <marker id="teaf-arrow-blue" markerWidth="10" markerHeight="10" refX="9" refY="5"
                  orient="auto" markerUnits="strokeWidth">
            <path d="M0,0 L10,5 L0,10 Z" fill="{t["primary"]}" />
          </marker>
        </defs>

        <g fill="none" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="137,210 137,75 351,75" stroke="{t["text"]}" stroke-width="2.4"
                    marker-end="url(#teaf-arrow-main)" />
          <line x1="531" y1="75" x2="630" y2="75" stroke="{t["text"]}" stroke-width="2.4"
                marker-end="url(#teaf-arrow-main)" />
          <line x1="842" y1="75" x2="941" y2="75" stroke="{t["text"]}" stroke-width="2.4"
                marker-end="url(#teaf-arrow-main)" />
          <line x1="1143" y1="75" x2="1242" y2="75" stroke="{t["text"]}" stroke-width="2.4"
                marker-end="url(#teaf-arrow-main)" />

          <line x1="235" y1="255" x2="424" y2="255" stroke="{t["primary"]}" stroke-width="3"
                marker-end="url(#teaf-arrow-blue)" />
          <polyline points="527,290 527,335 137,335 137,290" stroke="{t["primary"]}"
                    stroke-width="3" marker-end="url(#teaf-arrow-blue)" />
        </g>

        <g stroke-width="1.4">
          <rect x="45" y="210" width="185" height="80" rx="10" fill="#e8f1ff" stroke="#93c5fd" />
          <rect x="430" y="210" width="195" height="80" rx="10" fill="#fff4e5" stroke="#f59e0b" />
          <rect x="355" y="46" width="170" height="58" rx="9" fill="#f3e8ff" stroke="#c084fc" />
          <rect x="636" y="46" width="200" height="58" rx="9" fill="#f3e8ff" stroke="#c084fc" />
          <rect x="947" y="46" width="190" height="58" rx="9" fill="#ffe8e8" stroke="#fca5a5" />
          <rect x="1248" y="46" width="215" height="58" rx="9" fill="#eafaef" stroke="#86efac" />
        </g>

        <g font-family="Arial, Helvetica, sans-serif" font-size="14" text-anchor="middle" fill="#111827">
          <text x="137" y="240"><tspan x="137">Coaching Agent</tspan><tspan x="137" dy="18">(decide: mode +</tspan><tspan x="137" dy="18">needs_domain)</tspan></text>
          <text x="527" y="240"><tspan x="527">Domain Agent</tspan><tspan x="527" dy="18">(RAG + anomaly</tspan><tspan x="527" dy="18">detection)</tspan></text>
          <text x="440" y="80">Self-reflection</text>
          <text x="736" y="71"><tspan x="736">Tacit externalisation</tspan><tspan x="736" dy="17">by self-reflection</tspan></text>
          <text x="1042" y="71"><tspan x="1042">Human approval /</tspan><tspan x="1042" dy="17">rejection</tspan></text>
          <text x="1355" y="71"><tspan x="1355">Add to externalised</tspan><tspan x="1355" dy="17">tacit channel of agent</tspan></text>
        </g>

        <g font-family="Arial, Helvetica, sans-serif" font-size="13" font-weight="700" text-anchor="middle">
          <text x="330" y="230" class="teaf-flow-blue"><tspan x="330">TRIGGER A:</tspan><tspan x="330" dy="16">needs_domain = true</tspan></text>
          <text x="332" y="360" class="teaf-flow-blue">domain knowledge</text>
          <text x="250" y="140" class="teaf-flow-label"><tspan x="250">TRIGGER B:</tspan><tspan x="250" dy="16">{reflect_when}</tspan></text>
          <text x="1192" y="58" class="teaf-flow-label">if approved</text>
        </g>
      </svg>
    </div>
    </body>
    </html>
    """


def _reflection_prompt_editor() -> None:
    defaults = reflection.default_reflection_prompts()
    coaching_key = config.SETTING_REFLECTION_PROMPT_COACHING
    domain_key = config.SETTING_REFLECTION_PROMPT_DOMAIN
    instruction_key = config.SETTING_REFLECTION_PROMPT_INSTRUCTION
    current = {
        coaching_key: str(store.get_setting(coaching_key, defaults[coaching_key])),
        domain_key: str(store.get_setting(domain_key, defaults[domain_key])),
        instruction_key: str(store.get_setting(instruction_key, defaults[instruction_key])),
    }

    st.subheader("Reflection prompts")
    st.caption(
        "The Coaching Agent runs both reflection passes over the coaching conversation: "
        "one pass looks for additions to the Coaching Agent prompt, and one pass looks "
        "for additions to the Domain Agent prompt. Each pass uses its target prompt plus "
        "the shared output instruction."
    )
    with st.form("reflection_prompts"):
        coaching_prompt = st.text_area(
            "Coaching Agent reflection prompt",
            value=current[coaching_key],
            height=150,
        )
        domain_prompt = st.text_area(
            "Domain Agent reflection prompt",
            value=current[domain_key],
            height=150,
        )
        instruction_prompt = st.text_area(
            "Shared reflection output instruction",
            value=current[instruction_key],
            height=180,
        )
        save = st.form_submit_button("Save reflection prompts", type="primary")
        reset = st.form_submit_button("Reset reflection prompts to defaults", type="primary")
        if save:
            store.set_setting(coaching_key, coaching_prompt)
            store.set_setting(domain_key, domain_prompt)
            store.set_setting(instruction_key, instruction_prompt)
            st.session_state["interaction_save_notice"] = "Saved reflection prompts."
            st.rerun()
        if reset:
            for key, value in defaults.items():
                store.set_setting(key, value)
            st.session_state["interaction_save_notice"] = "Reset reflection prompts."
            st.rerun()


def _consolidation_prompt_editor() -> None:
    default = reflection.default_consolidation_prompt()
    key = config.SETTING_CONSOLIDATION_PROMPT
    current = str(store.get_setting(key, default))

    st.subheader("Patch consolidation prompt")
    st.caption(
        "Used by the per-agent **Consolidate pending** action under Tacit "
        "Externalisation. One prompt serves both agents: it merges an agent's pending "
        "reflection patches into a single de-duplicated patch."
    )
    with st.form("consolidation_prompt"):
        consolidation_prompt = st.text_area(
            "Consolidation prompt", value=current, height=170,
        )
        save = st.form_submit_button("Save consolidation prompt", type="primary")
        reset = st.form_submit_button("Reset consolidation prompt to default", type="primary")
        if save:
            store.set_setting(key, consolidation_prompt)
            st.session_state["interaction_save_notice"] = "Saved consolidation prompt."
            st.rerun()
        if reset:
            store.set_setting(key, default)
            st.session_state["interaction_save_notice"] = "Reset consolidation prompt."
            st.rerun()


def render() -> None:
    notice = st.session_state.pop("interaction_save_notice", None)
    if notice:
        st.toast(notice, icon="✅")
    every_n = int(store.get_setting(config.SETTING_REFLECTION_EVERY_N, config.DEFAULT_REFLECTION_EVERY_N_TURNS))
    # End-of-session reflection always runs, so the diagram always shows it.
    components.html(_flow_diagram_html(every_n, at_end=True), height=360, scrolling=False)
    st.caption("Trigger A is the judgement-driven domain call. Trigger B is the turn-driven "
               "self-reflection path; its timing label updates with the settings below.")

    st.divider()

    # --- Trigger A first ------------------------------------------------------
    st.subheader("Trigger A — domain calls (judgement-driven, NOT configurable)")
    st.markdown(
        "On every turn the **Coaching Agent** returns a structured judgement "
        "`{mode, needs_domain, domain_query, message}`. When it decides it needs "
        "factual domain analysis (a policy detail, a compliance requirement, an "
        "interpretation of an anomaly), it sets `needs_domain = true` and writes a "
        "precise `domain_query`. The orchestrator then calls the **Domain Agent** "
        "(which pulls RAG + the active anomaly payload) and calls the coach **again** "
        "with those findings folded in, to produce the final reply.\n\n"
        "This is **judgement-driven, not turn-based**, and that is the point in the "
        "thesis: orchestrating the domain agent is itself a *knowledge-informed act*, "
        "not a mechanical relay. Exposing it as an interval/threshold would reduce a "
        "framework contribution to a turn counter — so it is intentionally **not** a "
        "setting here."
    )

    st.divider()

    # --- Trigger B second (configurable) -------------------------------------
    st.subheader("Trigger B — self-reflection (turn-driven, configurable)")
    st.markdown(
        "Periodically the coach reflects on the session transcript and **externalises** "
        "a structured prompt patch. Patches are saved as **pending** and never "
        "auto-applied — a human approves them under **Settings → Tacit Externalisation**. This is "
        "the runtime SECI loop with meta-level human governance.\n\n"
        "Reflection always runs **at session end**; the interval below adds optional "
        "turn-driven reflection during the conversation."
    )
    with st.form("trigger_b"):
        n = st.number_input(
            "Reflect every N turns (0 disables turn-driven reflection)",
            min_value=0, max_value=100, value=every_n, step=1,
        )
        if st.form_submit_button("Save", type="primary"):
            store.set_setting(config.SETTING_REFLECTION_EVERY_N, int(n))
            st.session_state["interaction_save_notice"] = "Saved interaction trigger settings."
            st.rerun()

    st.divider()
    _reflection_prompt_editor()

    st.divider()
    _consolidation_prompt_editor()
