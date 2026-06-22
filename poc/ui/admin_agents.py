"""Admin — per-agent configuration (TEAF Components 2 & 3).

The topology is fixed: exactly one Coaching Agent and one Domain Agent. For each,
assign a registered model and edit the system prompt (the tacit knowledge channel).
RAG attachment + visibility flags arrive in Phase 2/6.
"""
import streamlit as st

import config
from teaf import models, store


def render() -> None:
    notice = st.session_state.pop("agent_save_notice", None)
    if notice:
        st.toast(notice, icon="✅")
    st.caption(
        "Fixed two-agent topology: one Coaching Agent, one Domain Agent. "
        "No arbitrary roles or extra agents (deliberate scope limit). The Coaching "
        "Agent owns externalisation reflection for both target agents because the "
        "human-facing coaching conversation is the source being reflected on."
    )

    model_rows = store.list_models()
    model_choices = {0: "— none —"} | {m["id"]: models.label(m) for m in model_rows}

    for a in store.list_agents():
        if a["role"] == config.ROLE_COACHING:
            label = "Coaching Agent"
            role_desc = "modes: coaching, facilitation, consulting"
        else:
            label = "Domain Agent"
            role_desc = "role: domain knowledge expert"
        with st.expander(f"{label}  ·  {role_desc}", expanded=True):
            ids = list(model_choices.keys())
            current = a["model_id"] or 0
            idx = ids.index(current) if current in ids else 0
            chosen = st.selectbox(
                "Conversation model",
                ids,
                index=idx,
                format_func=lambda i: model_choices[i],
                key=f"model_for_{a['id']}",
            )
            reflection_chosen = None
            if a["role"] == config.ROLE_COACHING:
                reflection_current = a["reflection_model_id"] or 0
                reflection_idx = ids.index(reflection_current) if reflection_current in ids else 0
                reflection_chosen = st.selectbox(
                    "Externalisation reflection model",
                    ids,
                    index=reflection_idx,
                    format_func=lambda i: model_choices[i],
                    key=f"reflection_model_for_{a['id']}",
                    help=(
                        "Used by the Coaching Agent for both reflection passes: one "
                        "targeting the Coaching Agent prompt and one targeting the "
                        "Domain Agent prompt."
                    ),
                )
            prompt = st.text_area(
                "System prompt",
                value=a["system_prompt"],
                height=300,
                key=f"prompt_for_{a['id']}",
            )
            if st.button("Save", type="primary", key=f"save_agent_{a['id']}"):
                fields = {"model_id": (chosen or None), "system_prompt": prompt}
                if a["role"] == config.ROLE_COACHING:
                    fields["reflection_model_id"] = reflection_chosen or None
                store.update_agent(a["id"], **fields)
                st.session_state["agent_save_notice"] = f"Saved {label}."
                st.rerun()
