"""Settings page"""
import shutil

import streamlit as st

import config
from teaf import store
from teaf.explicit_channels import anomaly, rag
from ui import admin_agents, admin_interaction, admin_models


def _delete_conversations() -> None:
    store.clear_conversations()


def _delete_patches() -> None:
    store.clear_patches()
    if config.PATCHES_DIR.exists():
        shutil.rmtree(config.PATCHES_DIR, ignore_errors=True)
    config.PATCHES_DIR.mkdir(parents=True, exist_ok=True)


def _delete_tasks() -> None:
    store.clear_governance_tasks()


def _delete_all() -> None:
    store.clear_all_user_data()
    rag.clear_store()
    anomaly.clear_cache()
    for d in (config.PATCHES_DIR, config.PORTFOLIO_DIR):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)


def _confirm_delete(key: str, label: str, helptext: str, action) -> None:
    with st.container(border=True):
        st.markdown(f"**{label}**")
        st.caption(helptext)
        typed = st.text_input("Type `yes` to confirm", key=f"confirm_{key}")
        if st.button("Delete", key=f"btn_{key}", type="primary"):
            if typed.strip().lower() == "yes":
                action()
                st.success(f"Done — {label.lower()}.")
                st.rerun()
            else:
                st.error("Type `yes` to confirm.")


def _data_management() -> None:
    st.caption(
        "Delete stored data for testing. These remove **user data**; registered models "
        "and the two agents are kept."
    )
    _confirm_delete("conv", "Delete conversation histories",
                    "Removes all sessions and messages.", _delete_conversations)
    _confirm_delete("patch", "Delete Tacit Externalisations",
                    "Removes all Tacit Externalisation records and their files on disk.", _delete_patches)
    _confirm_delete("tasks", "Delete all tasks",
                    "Removes every pending, approved, and rejected governance task.", _delete_tasks)
    _confirm_delete("all", "Delete all data",
                    "Removes conversations, governance tasks, Tacit Externalisations, settings, the vector store, "
                    "and the portfolio datasets (keeps registered models and agents).", _delete_all)


def _appearance() -> None:
    st.caption("Theme changes apply immediately and persist in app settings.")
    saved = str(store.get_setting(config.SETTING_LIGHT_MODE, "1")) == "1"
    before = bool(st.session_state.get("light_mode", saved))
    if "appearance_light_mode" not in st.session_state:
        st.session_state["appearance_light_mode"] = before
    after = st.toggle("Light mode", key="appearance_light_mode")
    if after != before or after != saved:
        st.session_state["light_mode"] = after
        store.set_setting(config.SETTING_LIGHT_MODE, "1" if after else "0")
        st.toast("Appearance updated.", icon="✅")
        st.rerun()


def render() -> None:
    st.title("⚙️ Settings")
    # Keyed container so one CSS rule styles every button here, no per-button styling.
    with st.container(key="options_panel"):
        tabs = st.tabs(["Appearance", "Models & API keys", "Agents", "Interaction triggers", "Data Management"])
        with tabs[0]:
            _appearance()
        with tabs[1]:
            admin_models.render()
        with tabs[2]:
            admin_agents.render()
        with tabs[3]:
            admin_interaction.render()
        with tabs[4]:
            _data_management()
