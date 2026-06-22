"""Admin page: register and edit models and API keys. Keys are stored in the DB."""
import time

import streamlit as st

import config
from teaf import llm, models, store


def _test_model(m) -> None:
    """Function to check if the registered LLM work."""
    t0 = time.perf_counter()
    try:
        reply = llm.chat(
            m["provider"], m["model_string"], m["api_key"],
            "You are a connectivity test.",
            [{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=16,
        )
        dt = (time.perf_counter() - t0) * 1000
        st.success(f"✓ {m['provider']} / {m['model_string']}  ·  {dt:.0f} ms")
        st.code(reply or "(empty response)")
    except Exception as e:  # show the real error verbatim, do not swallow
        dt = (time.perf_counter() - t0) * 1000
        st.error(f"✗ {m['provider']} / {m['model_string']}  ·  {dt:.0f} ms")
        st.code(str(e))


def _add_form() -> None:
    with st.form("add_model", clear_on_submit=True):
        st.subheader("Register a model")
        c1, c2 = st.columns(2)
        name = c1.text_input("Friendly name", placeholder="Claude Sonnet (prod)")
        provider = c2.selectbox("Provider", config.PROVIDERS)
        c3, c4 = st.columns(2)
        model_string = c3.text_input(
            "Model string",
            placeholder="claude-sonnet-4-6" if provider == config.PROVIDER_ANTHROPIC else "gpt-4o",
        )
        api_key = c4.text_input("API key (optional — blank = use .env)", type="password")
        if st.form_submit_button("Add model", type="primary"):
            if not name.strip() or not model_string.strip():
                st.error("Name and model string are required.")
            else:
                store.add_model(name.strip(), provider, model_string.strip(), api_key.strip() or None)
                st.session_state["model_save_notice"] = f"Registered {name}."
                st.rerun()


def _edit_card(m) -> None:
    with st.expander(f"✏️ {m['name']} · {m['provider']}/{m['model_string']}  (key: {models.masked_key(m['api_key'])})"):
        with st.form(f"edit_model_{m['id']}"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Friendly name", value=m["name"], key=f"nm_{m['id']}")
            provider = c2.selectbox(
                "Provider", config.PROVIDERS,
                index=config.PROVIDERS.index(m["provider"]) if m["provider"] in config.PROVIDERS else 0,
                key=f"pv_{m['id']}",
            )
            model_string = st.text_input("Model string", value=m["model_string"], key=f"ms_{m['id']}")
            new_key = st.text_input(
                "Replace API key (blank = keep current)", type="password", key=f"ak_{m['id']}"
            )
            clear_key = st.checkbox("Clear stored key (use .env instead)", key=f"ck_{m['id']}")
            cols = st.columns(2)
            if cols[0].form_submit_button("Save changes", type="primary"):
                if not name.strip() or not model_string.strip():
                    st.error("Name and model string are required.")
                else:
                    if clear_key:
                        key_arg = None
                    elif new_key.strip():
                        key_arg = new_key.strip()
                    else:
                        key_arg = store.KEEP_KEY
                    store.update_model(m["id"], name.strip(), provider, model_string.strip(), api_key=key_arg)
                    st.session_state["model_save_notice"] = f"Saved {name}."
                    st.rerun()
            if cols[1].form_submit_button("Delete", type="primary"):
                store.delete_model(m["id"])
                st.session_state["model_save_notice"] = f"Deleted {m['name']}."
                st.rerun()

        # Connectivity test (outside the form: a real minimal call via the wrapper).
        if st.button("🔌 Test", key=f"test_{m['id']}", type="primary", help="Make a real minimal call to check credentials/connectivity"):
            with st.spinner("Testing…"):
                _test_model(m)


def render() -> None:
    notice = st.session_state.pop("model_save_notice", None)
    if notice:
        st.toast(notice, icon="✅")
    st.caption(
        "Provider-agnostic registry (Anthropic + OpenAI). Edit a model to swap which "
        "model an agent uses. Keys can also come from poc/.env; keys here are stored "
        "locally and never committed."
    )

    _add_form()

    st.divider()
    st.subheader("Registered models")
    rows = store.list_models()
    if not rows:
        st.info("No models yet. Register one above (or rely on .env keys once assigned).")
        return
    for m in rows:
        _edit_card(m)
