# This component is documented and explained in the thesis. The comments here
# cover technical detail that may not be in the thesis.
from __future__ import annotations

import inspect
import json
import threading

import config
from teaf import llm, reflection, store
from teaf.agents import coaching_agent, domain_agent
from teaf.explicit_channels import anomaly

_REFLECTION_JOBS: set[tuple[int, int]] = set()


def conversation_history(session_id: int) -> list[dict]:
    # Domain and system messages are background only, excluded from the coach's context.
    history = []
    for m in store.list_messages(session_id):
        if m["role"] == "user":
            history.append({"role": "user", "content": m["content"]})
        elif m["role"] == "coaching":
            history.append({"role": "assistant", "content": m["content"]})
    return history[-config.MAX_CHAT_HISTORY_MESSAGES:]


def handle_user_turn(session_id: int, user_text: str, forced_mode: str | None = None,
                     on_phase=None) -> dict:
    # forced_mode lets a user-corrected mode override the agent's choice for this turn.
    # on_phase keeps one UI indicator alive across the whole turn.
    def _phase(label, detail=None):
        if on_phase:
            on_phase(label, detail)

    _phase("Coaching agent reasoning…")
    turn = store.max_turn(session_id) + 1
    store.add_message(session_id, turn, "user", user_text)
    _trace(session_id, turn, "User input received", user_text)
    history = conversation_history(session_id)

    # A corrected mode is fed in as context so the reply is produced in that mode, not just tagged.
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
        store.add_message(session_id, turn, "system", f"User corrected mode to {forced_mode}")

    # Trigger A, judgement-driven.
    try:
        decision = coaching_agent.decide(decide_input)
    except llm.LLMError as e:
        message = (
            "I could not complete that turn because the model call failed or timed out. "
            f"Details: {e}"
        )
        store.add_message(session_id, turn, "coaching", message, mode=config.MODE_COACHING)
        _trace(session_id, turn, "Coaching Agent decision failed", str(e), "failed")
        _trace(session_id, turn, "Response returned", message)
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
        _trace(session_id, turn, "Response pipeline failed", str(e), "failed")
        _trace(session_id, turn, "Response returned", message)
        return {
            "mode": config.MODE_COACHING,
            "message": message,
            "used_domain": False,
            "domain": None,
            "reflection": None,
        }
    mode = forced_mode if forced_mode in config.MODES else decision["mode"]
    _trace_coaching_rag(session_id, turn, decision.get("_process", {}).get("coaching_rag"))
    routing_detail = (
        f"**Selected mode:** `{mode}`\n\n"
        f"**Domain consultation required:** {'yes' if decision['needs_domain'] else 'no'}"
    )
    if decision.get("domain_query"):
        routing_detail += f"\n\n**Domain query:**\n\n{decision['domain_query']}"
    _trace(session_id, turn, "Coaching Agent made its routing decision", routing_detail)
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
        else:
            _trace(
                session_id,
                turn,
                "Domain Agent not consulted",
                "The Coaching Agent determined that this turn could be answered directly.",
                "skipped",
            )
            _trace(
                session_id,
                turn,
                "Coaching Agent composed a direct response",
                f"Mode: `{mode}`",
            )

    store.add_message(session_id, turn, "coaching", message, mode=mode)
    _trace(session_id, turn, "Response returned", message)

    # Trigger B, turn-driven reflection: produces a pending patch, never auto-applied,
    # and a failure here never breaks the conversation.
    reflected = _maybe_reflect(session_id, turn)
    if reflected:
        _trace(
            session_id,
            turn,
            "Tacit-knowledge reflection queued",
            "The configured turn interval was reached. Reflection runs in the background and any usable additions enter human review as pending patches.",
        )
    else:
        _trace(
            session_id,
            turn,
            "Turn-based reflection not triggered",
            "The configured reflection interval was not reached for this turn. Reflection still runs when the session is ended.",
            "skipped",
        )
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
    # Reflection always runs at session end and a failure here is non-fatal.
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
        _trace(session_id, turn, "Domain Agent consultation started", domain_query)
        try:
            payload = anomaly.get_payload()
        except Exception:
            payload = None
        _trace(
            session_id,
            turn,
            "Active anomaly evidence prepared",
            _json_detail(payload) if payload else "No active anomaly payload was available.",
            "completed" if payload else "skipped",
        )
        domain_result = domain_agent.answer(domain_query, anomaly_payload=payload)
    except Exception as e:  # domain unavailable (e.g. no model) - do not pretend
        store.add_message(session_id, turn, "system", f"Domain analysis unavailable: {e}")
        _trace(session_id, turn, "Domain Agent consultation failed", str(e), "failed")
        return _domain_failure_message(e), None

    domain_detail = _format_domain(domain_query, domain_result)
    store.add_message(session_id, turn, "domain", domain_detail)
    _trace_domain_result(session_id, turn, domain_result)
    phase("Composing response...", domain_detail)
    _trace(
        session_id,
        turn,
        "Domain findings passed to the Coaching Agent",
        "The complete Domain Agent result was injected as background evidence for the final coaching pass.",
    )
    try:
        final_rag_trace: dict = {}
        if "process_trace" in inspect.signature(coaching_agent.finalize).parameters:
            message = coaching_agent.finalize(
                decide_input, domain_query, domain_result, mode, process_trace=final_rag_trace
            )
        else:  # compatibility with test doubles and external integrations
            message = coaching_agent.finalize(decide_input, domain_query, domain_result, mode)
        _trace_coaching_rag(
            session_id,
            turn,
            final_rag_trace,
            title="Coaching knowledge injected for final composition",
        )
        _trace(session_id, turn, "Coaching Agent composed the final response", f"Mode: `{mode}`")
    except Exception as e:
        store.add_message(session_id, turn, "system", f"Coaching finalisation unavailable: {e}")
        _trace(session_id, turn, "Final response composition failed", str(e), "failed")
        message = (
            "I reached the domain analysis, but the final coaching pass failed. "
            "I will not pretend that the full response completed. Here is the "
            f"domain result I did retrieve:\n\n{domain_result.get('answer', '')}"
        )
    return message, domain_result


def _trace(session_id: int, turn: int, title: str, detail: str | None = None,
           status: str = "completed") -> None:
    """Tracing is observational: a storage fault must never break a user turn."""
    try:
        store.add_process_step(session_id, turn, title, detail, status)
    except Exception:
        pass


def _trace_coaching_rag(session_id: int, turn: int, rag_trace: dict | None,
                        title: str = "Coaching RAG knowledge injected") -> None:
    if not rag_trace:
        _trace(
            session_id, turn, title,
            "Retrieval details were not available for this execution path.", "skipped",
        )
        return
    hits = rag_trace.get("hits") or []
    errors = rag_trace.get("errors") or []
    lines = [f"**Retrieval query:** {rag_trace.get('query') or '(empty)'}"]
    if hits:
        lines.append("\n**Injected excerpts:**")
        for hit in hits:
            lines.append(f"\n- `{hit.get('source', '?')}`\n\n  {hit.get('text', '')}")
    else:
        lines.append("\nNo coaching-document chunks were retrieved.")
    if errors:
        lines.append("\n**Retrieval warnings:** " + "; ".join(str(e) for e in errors))
    _trace(session_id, turn, title, "\n".join(lines), "completed" if hits else "skipped")


def _trace_domain_result(session_id: int, turn: int, result: dict) -> None:
    parts = []
    sources = result.get("sources") or []
    parts.append("**Sources used:** " + (", ".join(f"`{s}`" for s in sources) or "none"))
    parts.append(f"**Anomaly payload used:** {'yes' if result.get('anomaly_used') else 'no'}")
    parts.append(f"**Portfolio records used:** {'yes' if result.get('records_used') else 'no'}")
    if result.get("portfolio_query"):
        parts.append(f"**Read-only portfolio SQL:**\n\n```sql\n{result['portfolio_query']}\n```")
    chunks = result.get("retrieved_chunks") or []
    if chunks:
        parts.append("**Retrieved governance excerpts:**")
        for hit in chunks:
            parts.append(f"- `{hit.get('source', '?')}`\n\n  {hit.get('text', '')}")
    if result.get("retrieval_errors"):
        parts.append("**Retrieval warnings:** " + "; ".join(result["retrieval_errors"]))
    parts.append("**Complete Domain Agent response:**\n\n" + str(result.get("answer", "")))
    _trace(session_id, turn, "Domain Agent returned its analysis", "\n\n".join(parts))


def _json_detail(value) -> str:
    return "```json\n" + json.dumps(value, indent=2, default=str) + "\n```"


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
