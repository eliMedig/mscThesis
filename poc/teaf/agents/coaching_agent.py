# This component is documented and explained in the thesis. The comments here
# cover technical detail that may not be in the thesis.
from __future__ import annotations

import config
from teaf import llm
from teaf.agents.base import Agent
from teaf.explicit_channels import rag

# Trigger A schema, enforced via provider-native structured output.
_DECISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "mode": {"type": "string", "enum": list(config.MODES)},
        "needs_domain": {"type": "boolean"},
        "domain_query": {"type": ["string", "null"]},
        "message": {"type": ["string", "null"]},
    },
    "required": ["mode", "needs_domain", "domain_query", "message"],
}

_DECISION_INSTRUCTION = """

=== OUTPUT FORMAT (MANDATORY) ===
Respond with ONE JSON object and nothing else:
{
  "mode": "coaching" | "facilitation" | "consulting",
  "needs_domain": true | false,
  "domain_query": string or null,
  "message": string or null
}
Rules:
- Choose "mode" from the knowledge asymmetry right now (it is a judgement).
- Set "needs_domain" true ONLY when you need factual EA-governance domain analysis
  (policy detail, compliance requirement, anomaly interpretation). Then write a
  precise "domain_query" and you MAY set "message" to null (a final reply will be
  produced after the domain analysis returns).
- Also set "needs_domain" true for requests to inspect portfolio/application data,
  show raw app records, count or explain anomaly flags, quote policy text, or answer
  questions about uploaded governance documents.
- NEVER set "needs_domain" for questions about coaching practice, coaching frameworks
  (ICF/EMCC/AC), facilitation/questioning technique, or the contents of your coaching
  documents. Your coaching knowledge is injected into this prompt; answer those
  directly in "message".
- Otherwise set "needs_domain" false, "domain_query" null, and put your reply to the
  practitioner in "message".
- Do not tell the practitioner you will pull/check/look up data unless you set
  "needs_domain" true in the same JSON object.
- If "needs_domain" is false, "message" must be the complete final answer for the
  user. It must not be a status update, retrieval promise, or future-tense plan.
"""

_RESPONSE_STYLE_INSTRUCTION = """

=== RESPONSE STYLE ===
- Keep user-facing replies concise, specific, and conversational.
- Prefer 2-4 short paragraphs or a short list only when it genuinely helps.
- Do not use large markdown headings in normal chat replies.
- Ask one focused next question unless the practitioner explicitly asks for a detailed list or explanation.
- Expand only when the practitioner asks for more detail, examples, or a full analysis.

=== COACHING POSTURE ===
- Prefer coaching when the practitioner has enough context to make the judgement.
- Never make governance decisions for the practitioner; keep decision ownership with the human.
- If the conversation becomes too directive, return the human to the loop by surfacing evidence,
  options, and one focused criterion question.
- If the practitioner starts without a clear goal, do not assume APM/anomaly work. Briefly offer:
  EA governance document support, APM anomaly checks, decision facilitation, or coaching through
  an ambiguous governance issue. Ask what they want to focus on.
"""


def decide(history: list[dict]) -> dict:
    """Trigger A: return {mode, needs_domain, domain_query, message}, normalised."""
    agent = _agent()
    latest_user = _latest_user_text(history)
    rag_trace: dict = {}
    system = _system_prompt(agent, latest_user, rag_trace) + _RESPONSE_STYLE_INSTRUCTION + _DECISION_INSTRUCTION
    raw = agent.complete_json(
        system,
        history,
        max_tokens=1024,
        schema=_DECISION_SCHEMA,
        name="emit_coaching_decision",
    )
    decision = _normalise(raw)
    decision["_process"] = {"coaching_rag": rag_trace}
    violation = _message_claims_lookup(decision["message"])
    if not decision["needs_domain"] and (
        _requires_domain(latest_user) or violation
    ):
        decision["needs_domain"] = True
        decision["domain_query"] = latest_user
        decision["message"] = None
        decision["contract_violation"] = (
            "retrieval_intent_without_delegation" if violation else "auto_delegated"
        )
    return decision


def finalize(history: list[dict], domain_query: str, domain_result: dict, mode: str,
             process_trace: dict | None = None) -> str:
    """Second call: produce the user-facing reply with domain findings folded in."""
    agent = _agent()
    sources = ", ".join(domain_result.get("sources") or []) or "none"
    injected = (
        "[BACKGROUND: domain analysis you requested; the practitioner cannot see this]\n"
        f"Query: {domain_query}\n"
        f"Findings: {domain_result.get('answer', '')}\n"
        f"Sources: {sources}\n\n"
        f"Now reply to the practitioner in {mode.upper()} mode. Integrate the factual "
        "findings where useful, but keep ownership of the decision with the practitioner. "
        "Do not mention this background note or the domain agent. Keep the reply concise, "
        "specific, and conversational. Do not use large markdown headings unless the "
        "practitioner explicitly asks for a structured report. Keep ownership of the "
        "decision with the practitioner."
    )
    messages = list(history) + [{"role": "user", "content": injected}]
    m = agent._require_model()
    text = llm.chat(
        m["provider"], m["model_string"], m["api_key"],
        _system_prompt(
            agent,
            domain_query or _latest_user_text(history),
            process_trace,
        ) + _RESPONSE_STYLE_INSTRUCTION,
        messages,
    )
    if not message_claims_lookup(text):
        return text

    repair = (
        "Your previous draft contained retrieval-intent phrasing. That violates the "
        "delegation contract because the domain result is already provided below. "
        "Answer the practitioner now using only the provided domain result. Do not "
        "promise to retrieve, pull, fetch, look up, get, check, or list anything later.\n\n"
        f"Domain result:\n{domain_result.get('answer', '')}"
    )
    return llm.chat(
        m["provider"], m["model_string"], m["api_key"],
        _system_prompt(agent, domain_query or _latest_user_text(history)) + _RESPONSE_STYLE_INSTRUCTION,
        list(history) + [{"role": "user", "content": repair}],
    )


# --- helpers ------------------------------------------------------------------
def _agent() -> Agent:
    agent = Agent.load(config.ROLE_COACHING)
    if agent is None:  # pragma: no cover - seeded on init
        raise RuntimeError("Coaching agent is not seeded.")
    return agent


def _system_prompt(agent: Agent, query: str | None = None,
                   process_trace: dict | None = None) -> str:
    prompt = agent.system_prompt or ""
    if "HARD DELEGATION CONTRACT:" not in prompt:
        prompt = config.DELEGATION_CONTRACT.strip() + "\n\n" + prompt
    return prompt + _coaching_rag_context(agent, query, trace=process_trace)


def _coaching_rag_context(agent: Agent, query: str | None, k: int = 3,
                          trace: dict | None = None) -> str:
    # Agent-scoped retrieval so the coach reads only its own coaching collections.
    query = (query or "").strip()
    if not query:
        return ""

    hits, errors = rag.retrieve_for_agent(agent.id, query, k=k)
    if trace is not None:
        trace.update({"query": query, "hits": hits, "errors": errors})

    parts: list[str] = []
    if hits:
        context = "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits)
        parts.append(
            "=== RETRIEVED COACHING RAG CONTENT "
            "(explicit coaching/framework guidance; not domain data) ===\n" + context
        )
    if errors:
        parts.append(
            "=== COACHING RAG WARNINGS ===\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\nUse your existing coaching prompt if this reference material is unavailable."
        )
    return "\n\n" + "\n\n".join(parts) if parts else ""


def _normalise(raw: dict) -> dict:
    mode = raw.get("mode")
    if mode not in config.MODES:
        mode = config.MODE_COACHING
    needs = bool(raw.get("needs_domain"))
    query = raw.get("domain_query") or None
    message = raw.get("message") or None
    if needs and not query:  # no query means the domain agent cannot be called
        needs = False
    return {
        "mode": mode,
        "needs_domain": needs,
        "domain_query": query,
        "message": message,
        "contract_violation": None,
    }


def _latest_user_text(history: list[dict]) -> str:
    for msg in reversed(history):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _is_coaching_question(q: str) -> bool:
    # Coaching questions are answered from the coach's own RAG, never force-delegated.
    coaching_terms = (
        "coaching",
        "coach",
        "icf",
        "emcc",
        "reflective",
        "questioning technique",
        "facilitation technique",
        "your document",
        "your documents",
        "your knowledge",
        "your framework",
        "coaching document",
        "coaching framework",
    )
    return any(term in q for term in coaching_terms)


def _requires_domain(text: str) -> bool:
    # Safety net: bare words like "document" or "owner" must not trigger, they also
    # describe the coaching knowledge base.
    q = (text or "").lower()
    if _is_coaching_question(q):
        return False
    governance_terms = (
        "policy",
        "policies",
        "governance",
        "compliance",
        "compliant",
        "anomaly",
        "anomalies",
        "outlier",
        "outliers",
        "portfolio",
        "csv",
    )
    if any(term in q for term in governance_terms):
        return True
    data_terms = ("show", "record", "raw", "field", "data", "one app", "single app", "app-")
    if ("app" in q or "application" in q) and any(term in q for term in data_terms):
        return True
    # Portfolio search, count, filter, and sort belong to the domain agent's SQL tool.
    if any(t in q for t in ("app", "application", "portfolio", "vendor", "supplier", "cost")) and any(
        t in q for t in ("list", "all ", "how many", "count", "number of", "which", "find",
                          "search", "any ", "vendor", "supplier", "category", "from ", "made by",
                          "over", "above", "under", "below", "more than", "greater", "less than",
                          "cost", "sort", "top ", "highest", "lowest", "expensive", "cheapest",
                          "average", "total", "sum", "group", " by ")
    ):
        return True
    # "owner"/"flag" only count as governance signals when tied to apps/portfolio.
    if any(term in q for term in ("owner", "ownership", "flag", "flags")) and (
        "app" in q or "application" in q or "portfolio" in q
    ):
        return True
    return False


def message_claims_lookup(message: str | None) -> bool:
    q = (message or "").lower()
    return any(
        phrase in q
        for phrase in (
            "let me pull",
            "i will pull",
            "i'll pull",
            "let me check",
            "i will check",
            "i'll check",
            "let me look up",
            "i will look up",
            "i'll look up",
            "let me retrieve",
            "i will retrieve",
            "i'll retrieve",
            "let me fetch",
            "i will fetch",
            "i'll fetch",
            "let me get",
            "i will get",
            "i'll get",
            "let me list",
            "i will list",
            "i'll list",
        )
    )


def _message_claims_lookup(message: str | None) -> bool:
    return message_claims_lookup(message)
