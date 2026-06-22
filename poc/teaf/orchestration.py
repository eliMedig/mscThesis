"""Orchestration — the turn loop and the two triggers (§7).

Two distinct triggers, deliberately NOT generalised into a rules engine:

  - Trigger A — domain calls (judgment-driven): the Coaching Agent returns
    structured output {mode, needs_domain, domain_query, message}. When
    needs_domain is true, the orchestrator calls the Domain Agent, then calls the
    Coaching Agent AGAIN with the domain response folded in. (Phase 2/3)
  - Trigger B — self-reflection (turn-driven): every N turns and/or at session
    end, run reflection.py to produce a human-approved prompt patch. (Phase 5)

A "turn" here is one user message and the coaching reply it produces; both share a
turn number so Trigger B can count exchanges.
"""
from __future__ import annotations

import threading

import config
from teaf import llm, reflection, store
from teaf.agents import coaching_agent, domain_agent
from teaf.explicit_channels import anomaly

_REFLECTION_JOBS: set[tuple[int, int]] = set()


def conversation_history(session_id: int) -> list[dict]:
    """Map persisted user/coaching messages to the wrapper's user/assistant history.

    Domain and system messages are background only and are not part of the
    coach's visible conversation context.
    """
    history = []
    for m in store.list_messages(session_id):
        if m["role"] == "user":
            history.append({"role": "user", "content": m["content"]})
        elif m["role"] == "coaching":
            history.append({"role": "assistant", "content": m["content"]})
    return history[-config.MAX_CHAT_HISTORY_MESSAGES:]


def handle_user_turn(session_id: int, user_text: str, forced_mode: str | None = None,
                     on_phase=None) -> dict:
    """Run one full turn. Persists user + (optional domain) + coaching messages.

    Returns {mode, message, used_domain, domain}. `forced_mode` (Phase 3) lets a
    user-corrected mode override the agent's choice for this turn. `on_phase(label)`
    (optional) is called as the turn moves through phases so the UI can keep one
    indicator visible for the WHOLE turn (coaching → domain → finalize).
    """
    def _phase(label, detail=None):
        if on_phase:
            on_phase(label, detail)

    _phase("Coaching agent reasoning…")
    turn = store.max_turn(session_id) + 1
    store.add_message(session_id, turn, "user", user_text)
    history = conversation_history(session_id)

    # Mode correction = additional EXPLICIT input (Phase 3). When the user overrides
    # the mode, we feed that as context into the coach's judgement so the reply is
    # actually produced in that mode (not just tagged), and record the correction.
    decide_input = list(history)
    if forced_mode in config.MODES:
        decide_input.append({
            "role": "user",
            "content": (
                f"[The practitioner has explicitly asked you to respond in "
                f"{forced_mode.upper()} mode for this turn. Honour that unless it would "
                f"violate a hard boundary.]"
            ),
        })
        store.add_message(session_id, turn, "system", f"User corrected mode → {forced_mode}")

    # Trigger A — judgement-driven.
    try:
        decision = coaching_agent.decide(decide_input)
    except llm.LLMError as e:
        message = (
            "I could not complete that turn because the model call failed or timed out. "
            f"Details: {e}"
        )
        store.add_message(session_id, turn, "coaching", message, mode=config.MODE_COACHING)
        return {
            "mode": config.MODE_COACHING,
            "message": message,
            "used_domain": False,
            "domain": None,
            "reflection": None,
        }
    except Exception as e:
        message = (
            "I could not complete that turn because the response pipeline hit an error. "
            f"Details: {e}"
        )
        store.add_message(session_id, turn, "coaching", message, mode=config.MODE_COACHING)
        return {
            "mode": config.MODE_COACHING,
            "message": message,
            "used_domain": False,
            "domain": None,
            "reflection": None,
        }
    mode = forced_mode if forced_mode in config.MODES else decision["mode"]
    if decision.get("contract_violation"):
        store.add_message(
            session_id,
            turn,
            "system",
            f"Delegation contract catch: {decision['contract_violation']}",
        )

    domain_result = None
    if decision["needs_domain"]:
        message, domain_result = _run_domain_exchange(
            session_id, turn, decide_input, decision["domain_query"], mode, _phase
        )
    else:
        message = decision["message"] or "Could you say a little more about that?"
        if coaching_agent.message_claims_lookup(message):
            store.add_message(
                session_id,
                turn,
                "system",
                "Delegation contract catch: final message contained retrieval intent without delegation.",
            )
            message, domain_result = _run_domain_exchange(
                session_id, turn, decide_input, user_text, mode, _phase
            )

    store.add_message(session_id, turn, "coaching", message, mode=mode)

    # Trigger B — turn-driven self-reflection (every N turns). Produces a PENDING
    # patch; never auto-applied. Failures here never break the conversation.
    reflected = _maybe_reflect(session_id, turn)
    return {
        "mode": mode,
        "message": message,
        "used_domain": domain_result is not None,
        "domain": domain_result,
        "reflection": reflected,
    }


def _maybe_reflect(session_id: int, turn: int) -> dict | None:
    try:
        n = int(store.get_setting(config.SETTING_REFLECTION_EVERY_N, config.DEFAULT_REFLECTION_EVERY_N_TURNS))
    except (TypeError, ValueError):
        n = config.DEFAULT_REFLECTION_EVERY_N_TURNS
    if n <= 0 or turn % n != 0:
        return None
    job_key = (session_id, turn)
    if job_key in _REFLECTION_JOBS:
        return {"queued": True}
    _REFLECTION_JOBS.add(job_key)

    def _run_reflection() -> None:
        try:
            reflection.reflect_on_session(session_id)
        except Exception:
            pass
        finally:
            _REFLECTION_JOBS.discard(job_key)

    threading.Thread(target=_run_reflection, daemon=True).start()
    return {"queued": True}


def end_session(session_id: int) -> dict | None:
    """End a session (Trigger B 'run at session end'). Reflection ALWAYS runs at
    session end, then the session is marked ended. Reflection failures are non-fatal."""
    reflected = None
    try:
        reflected = reflection.reflect_on_session(session_id)
    except Exception:
        reflected = None
    store.end_session(session_id)
    return reflected


def _run_domain_exchange(session_id: int, turn: int, decide_input: list[dict],
                         domain_query: str, mode: str, phase) -> tuple[str, dict | None]:
    try:
        # Dynamic explicit channel: hand the active anomaly payload to the
        # Domain Agent (it interprets the signals; it does not compute them).
        phase("Consulting domain agent...")
        try:
            payload = anomaly.get_payload()
        except Exception:
            payload = None
        domain_result = domain_agent.answer(domain_query, anomaly_payload=payload)
    except Exception as e:  # domain unavailable (e.g. no model) - do not pretend
        store.add_message(session_id, turn, "system", f"Domain analysis unavailable: {e}")
        return _domain_failure_message(e), None

    domain_detail = _format_domain(domain_query, domain_result)
    store.add_message(session_id, turn, "domain", domain_detail)
    phase("Composing response...", domain_detail)
    try:
        message = coaching_agent.finalize(decide_input, domain_query, domain_result, mode)
    except Exception as e:
        store.add_message(session_id, turn, "system", f"Coaching finalisation unavailable: {e}")
        message = (
            "I reached the domain analysis, but the final coaching pass failed. "
            "I will not pretend that the full response completed. Here is the "
            f"domain result I did retrieve:\n\n{domain_result.get('answer', '')}"
        )
    return message, domain_result


def _format_domain(query: str, result: dict) -> str:
    sources = ", ".join(result.get("sources") or []) or "none"
    flag = " (anomaly payload used)" if result.get("anomaly_used") else ""
    return f"Q: {query}{flag}\nA: {result.get('answer', '')}\nSources: {sources}"


def _domain_failure_message(error: Exception) -> str:
    return (
        "I tried to use the domain analysis path for that, but it failed before I "
        "could retrieve reliable evidence. I will not pretend I checked the data or "
        f"policy documents.\n\nTechnical detail: {error}"
    )
