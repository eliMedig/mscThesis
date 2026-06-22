"""Domain Agent — TEAF Component 3.

Background only — NEVER talks to the human. Receives a query from the Coaching
Agent, retrieves RAG content from its attached collection(s), incorporates the
active anomaly payload (Phase 4), and returns a structured, grounded response.

Returns: {"answer": str, "sources": [filenames], "anomaly_used": bool}.
The Domain Agent does NOT compute anomalies — it interprets the payload it is
handed (the separation matters; see README §design choices).
"""
from __future__ import annotations

import json
import re

import config
from teaf.agents.base import Agent
from teaf.explicit_channels import anomaly, rag


_DOMAIN_SOURCES_NOTE = (
    "\n\n=== YOUR THREE KNOWLEDGE SOURCES — route correctly ===\n"
    "1) Governance & policy DOCUMENTS (semantic RAG): what the policy/principle/standard "
    "requires, intake/onboarding gates, AI or public-facing app governance, anything "
    "referenced by document name. Ground these answers in the RETRIEVED POLICY CONTENT below.\n"
    "2) The application PORTFOLIO (structured, queried via SQL elsewhere): which apps, counts, "
    "costs, vendors, classifications, filters.\n"
    "3) ANOMALY-detection results (provided as a payload).\n"
    "For a policy/principle/standard/document question, answer from the retrieved documents — "
    "NEVER keyword-search or guess at the portfolio to answer it. If the documents genuinely do "
    "not cover the point, say so plainly; do not improvise policy."
)


def answer(query: str, anomaly_payload: dict | None = None, k: int = 4) -> dict:
    agent = Agent.load(config.ROLE_DOMAIN)
    if agent is None:  # pragma: no cover - seeded on init
        raise RuntimeError("Domain agent is not seeded.")

    # Any application / portfolio / anomaly question consolidates ALL THREE sources
    # (portfolio SQL + anomaly payload + governance RAG) into one grounded answer —
    # that fusion is where the domain agent's strength comes from.
    if _is_portfolio_search_query(query) or _mentions_anomaly(query):
        return _consolidated_answer(agent, query, anomaly_payload, k)

    # A pure policy / principle / standard / document question → semantic RAG over the
    # governance documents (never keyword-search the portfolio for a policy question).
    return _rag_answer(agent, query, anomaly_payload, k)


def _rag_answer(agent: Agent, query: str, anomaly_payload: dict | None, k: int) -> dict:
    """Answer from the governance-document RAG (hard channel isolation: domain
    collection only). The retrieved chunks are surfaced so routing is visible."""
    from teaf import llm

    hits, retrieval_errors = rag.retrieve_for_agent(agent.id, query, k=k)
    context = "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits) or "(no documents retrieved)"
    system = (
        agent.system_prompt + _DOMAIN_SOURCES_NOTE
        + "\n\n=== RETRIEVED POLICY CONTENT (ground your answer in this) ===\n" + context
    )
    if retrieval_errors:
        system += (
            "\n\n=== RETRIEVAL WARNINGS ===\n"
            + "\n".join(f"- {e}" for e in retrieval_errors)
            + "\nIf the retrieved policy content is empty because retrieval failed, say so explicitly. "
            "Do not answer from memory or imply that a policy document was checked."
        )
    if anomaly_payload:
        system += "\n\n=== ACTIVE ANOMALY PAYLOAD (interpret; do not recompute) ===\n" + json.dumps(
            anomaly_payload, indent=2
        )
    system += _EVIDENCE_REQUIREMENT

    m = agent._require_model()
    text = llm.chat(m["provider"], m["model_string"], m["api_key"], system, [{"role": "user", "content": query}])
    # Surface which document chunks were retrieved (routing visibility in the internal block).
    if hits:
        text += "\n\n" + _retrieved_footer(hits)
    return {
        "answer": text,
        "sources": sorted({h["source"] for h in hits}),
        "anomaly_used": bool(anomaly_payload),
        "records_used": False,
        "retrieval_errors": retrieval_errors,
    }


_CONSOLIDATION_INSTRUCTION = (
    "\n\n=== HOW TO ANSWER — CONSOLIDATE ALL THREE SOURCES ===\n"
    "Fuse the portfolio data, the anomaly results, and the governance documents into ONE "
    "coherent answer. For a question about an application, give: (a) its portfolio data, "
    "(b) whether the anomaly detector flagged it and why, and (c) what the governance "
    "documents require — and connect them explicitly (e.g. \"APP-0042 has no owner, which "
    "the anomaly detector flagged as missing_owner and which violates architecture_policy's "
    "ownership rule\"). The flagged-application rows below are the real records the anomaly "
    "ran on — use them to explain WHAT is wrong, not just THAT it is flagged. If a source "
    "genuinely has nothing on the point, say so; never invent data or policy."
)


def _consolidated_answer(agent: Agent, query: str, anomaly_payload: dict | None, k: int) -> dict:
    """Fuse ALL THREE sources: the portfolio (SQL over the real rows), the anomaly
    payload PLUS the portfolio rows for the flagged apps (the data the detector ran
    on), and the governance documents (RAG) — then synthesise one grounded answer."""
    from teaf import llm

    # 1) Portfolio (SQL) for the specific question — only when it has a data shape; a
    #    pure anomaly question ("list the outliers") leans on the flagged rows instead.
    sql_used, sql_block = _portfolio_sql_block(agent, query) if _is_portfolio_search_query(query) \
        else (None, "(not applicable to this question)")

    # 2) Cross-reference: the real portfolio rows for the flagged apps.
    flagged_ids = [
        f.get("app_id") for f in (anomaly_payload or {}).get("flagged_records") or [] if f.get("app_id")
    ]
    flagged_rows = anomaly.lookup_rows_by_ids(flagged_ids, limit=25) if flagged_ids else []

    # 3) Governance documents (RAG).
    hits, retrieval_errors = rag.retrieve_for_agent(agent.id, query, k=k)
    context = "\n\n".join(f"[{h['source']}] {h['text']}" for h in hits) or "(no documents retrieved)"

    system = (
        agent.system_prompt + _DOMAIN_SOURCES_NOTE
        + "\n\n=== PORTFOLIO SCHEMA + SAMPLE ROWS (the real data model + id format) ===\n"
        + anomaly.sample_rows(3)
        + "\n\n=== RETRIEVED POLICY CONTENT (ground policy claims in this) ===\n" + context
        + "\n\n=== PORTFOLIO QUERY RESULT (structured data; use these exact rows) ===\n" + sql_block
    )
    if flagged_rows:
        system += (
            "\n\n=== PORTFOLIO ROWS FOR FLAGGED APPLICATIONS (the data the anomaly ran on) ===\n"
            + json.dumps(flagged_rows, indent=2, default=str)
        )
    if anomaly_payload:
        system += "\n\n=== ACTIVE ANOMALY PAYLOAD (interpret; do not recompute) ===\n" + json.dumps(
            anomaly_payload, indent=2
        )
    system += _CONSOLIDATION_INSTRUCTION + _EVIDENCE_REQUIREMENT

    m = agent._require_model()
    text = llm.chat(m["provider"], m["model_string"], m["api_key"], system, [{"role": "user", "content": query}])
    if sql_used:
        text += f"\n\nPortfolio query used: `{sql_used}`"
    if hits:
        text += "\n\n" + _retrieved_footer(hits)
    return {
        "answer": text,
        "sources": sorted(
            {h["source"] for h in hits}
            | ({anomaly.CSV_NAME} if (sql_used or flagged_rows) else set())
            | ({"active_anomaly_payload"} if anomaly_payload else set())
        ),
        "anomaly_used": bool(anomaly_payload),
        "records_used": bool(sql_used or flagged_rows),
        "retrieval_errors": retrieval_errors,
    }


def _retrieved_footer(hits: list[dict]) -> str:
    docs = sorted({h["source"] for h in hits})
    return "🔎 Retrieved from governance documents: " + ", ".join(f"`{d}`" for d in docs)


_EVIDENCE_REQUIREMENT = (
    "\n\n=== EVIDENCE REQUIREMENT (mandatory) ===\n"
    "Always ground each statement in specific, named evidence and explain the reasoning:\n"
    "- For policy/standard claims, cite the source document by name, e.g. "
    "\"as stated in architecture_policy.txt, every application must have a named owner\".\n"
    "- For anomaly claims, cite the specific application id and reason from the payload, "
    "e.g. \"APM/app_id APP-0033 was flagged as retire_but_critical, which contradicts the "
    "lifecycle policy because...\".\n"
    "- Never assert something the retrieved documents or payload do not support; if the "
    "knowledge base does not cover it, say so explicitly.\n"
    "- The practitioner must be able to trace every point back to a document or a flagged record."
)


_ANOMALY_TERMS = ("outlier", "outliers", "anomaly", "anomalies", "flag", "flagged", "flags")


def _mentions_anomaly(query: str) -> bool:
    """True when the question is about anomaly-detection results — routes to the
    consolidated path so the payload + flagged rows + policy are fused."""
    q = (query or "").lower()
    return any(t in q for t in _ANOMALY_TERMS)


# --- structured portfolio query: the agent writes SQL, a read-only tool runs it -
_SQL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"sql": {"type": "string"}},
    "required": ["sql"],
}


_APP_ID_TOKEN = re.compile(r"\b[a-z]{2,}[-_ ]?\d{2,}\b")

# Governance/policy/document signals → semantic RAG over the governance collection
# (NOT the portfolio SQL path). Deliberately excludes bare "compliant"/"compliance"
# which are portfolio data-field values, not policy questions.
_POLICY_TERMS = (
    "policy", "policies", "governance", "govern", "principle", "principles",
    "standard", "standards", "guideline", "guidelines", "framework", "control",
    "controls", "mandate", "require", "required", "requirement", "requirements",
    "intake", "onboard", "onboarding", "gate", "approval", "approve", "regulation",
    "directive", "ai governance", "data classification policy", "retention",
    "document", "documentation", ".pdf", ".txt", "ea-gov", "entarch", "what does the policy",
)


def _is_policy_question(query: str) -> bool:
    """True for governance/policy/principle/standard/document questions that must be
    answered from the governance-document RAG, never the portfolio SQL table."""
    q = (query or "").lower()
    return any(t in q for t in _POLICY_TERMS)


# Multi-word data intents (specific enough to match as substrings).
_DATA_PHRASE_INTENTS = (
    "how many", "number of", "made by", "more than", "less than", "group by", "sorted by",
)
# Single-word data intents — matched on WORD boundaries so e.g. "over" does NOT match
# "g(over)nance" and "sum" does NOT match "(Sum)marise" (which would mis-route policy
# questions into the SQL path).
_DATA_WORD_INTENTS = (
    "list", "all", "count", "which", "find", "search", "any", "vendor", "vendors",
    "supplier", "suppliers", "category", "categories", "show", "details", "over",
    "above", "under", "below", "greater", "least", "cost", "costs", "sort", "sorted",
    "top", "highest", "lowest", "expensive", "cheapest", "average", "total", "sum", "group",
)
_DATA_WORD_RE = re.compile(r"\b(" + "|".join(_DATA_WORD_INTENTS) + r")\b")


def _is_portfolio_search_query(query: str) -> bool:
    q = (query or "").lower()
    if _APP_ID_TOKEN.search(q):  # an app-id-like token → a portfolio lookup
        return True
    if not any(t in q for t in ("app", "application", "portfolio", "vendor", "supplier", "category", "cost")):
        return False
    if any(p in q for p in _DATA_PHRASE_INTENTS):
        return True
    return bool(_DATA_WORD_RE.search(q))


def _sql_system_prompt(schema: dict, sample: str) -> str:
    """Build the SQL-writing prompt ENTIRELY from the live table schema + a few real
    sample rows. No column names are hardcoded — everything is derived from the actual
    data, so a portfolio swap (different fields/values) needs zero code changes. The
    sample rows show the exact id format and value spellings so the agent stops
    inventing ids like APP-180 when the real format is APP-0180."""
    cols = schema["columns"]
    col_lines = []
    for c in cols:
        samples = f" — e.g. {', '.join(c['samples'])}" if c["samples"] else ""
        col_lines.append(f"- {c['name']} ({c['type']}){samples}")

    text_cols = [c["name"] for c in cols if c["type"] == "TEXT"]
    numeric_cols = [c["name"] for c in cols if c["type"] == "NUMERIC"]
    examples = []
    if text_cols:
        examples.append(f"  keyword search → ... WHERE {text_cols[0]} LIKE '%term%'")
    if numeric_cols:
        n = numeric_cols[0]
        examples.append(f"  threshold + sort → ... WHERE {n} > 1000 ORDER BY {n} DESC")
    if text_cols:
        examples.append(f"  count by group → SELECT {text_cols[0]}, COUNT(*) AS n FROM {schema['table']} GROUP BY {text_cols[0]}")
    example_block = ("\nExamples (adapt to the real columns above):\n" + "\n".join(examples)) if examples else ""

    money_cols = [c["name"] for c in cols if any(t in c["name"].lower() for t in ("cost", "chf", "price", "amount", "spend"))]
    cost_note = ""
    if money_cols:
        cost_note = (
            f"\n- Monetary columns ({', '.join(money_cols)}) are in Swiss francs (CHF). Every value is "
            "already CHF — never add a currency caveat and never ask which currency."
        )
    return (
        "You translate the practitioner's question into exactly ONE read-only SQLite SELECT over a "
        f"single table named `{schema['table']}` ({schema['row_count']} rows).\n\n"
        "Columns (use these EXACT names — do not invent or assume other columns):\n"
        + "\n".join(col_lines) + "\n\n"
        "Example rows (header + first rows — copy the exact id format and value spellings):\n"
        + sample + "\n\n"
        "Rules:\n"
        "- Output ONE SELECT statement only — no other statements, no trailing semicolon.\n"
        f"- Only read the `{schema['table']}` table.\n"
        "- Keyword / name / vendor search uses LIKE with wildcards, case-insensitively across the "
        "relevant text columns.\n"
        "- Application ids use the EXACT format in the example rows (e.g. zero-padded). If the user "
        "gives a bare number or partial id (e.g. 'app 180'), match it with LIKE on the id column "
        "(e.g. ... LIKE '%180%') or reconstruct the full padded id — never compare against the bare number.\n"
        "- Numeric thresholds use real comparisons; sort with ORDER BY; counts use COUNT(*) + GROUP BY.\n"
        "- When listing individual applications, include the application id column among the selected columns."
        + cost_note + example_block
    )


def _portfolio_sql_block(agent: Agent, query: str) -> tuple[str | None, str]:
    """Generate + run the agent's SQL for the query; return (sql_used, result_block).
    Surfaces a failed query as text instead of crashing or returning opening rows."""
    from teaf import llm

    try:
        sql = _generate_portfolio_sql(agent, query)
        if not sql:
            return None, "(no portfolio query was produced)"
        result = anomaly.run_portfolio_sql(sql)
        block = json.dumps(
            {"sql": result["sql"], "total": result["total"], "rows": result["rows"]},
            indent=2, default=str,
        )
        return result["sql"], block
    except llm.LLMError:
        raise
    except Exception as e:
        return None, f"(portfolio query failed: {e})"


def _generate_portfolio_sql(agent: Agent, query: str) -> str | None:
    """Have the agent emit ONE read-only SELECT for the query, schema-driven. Returns
    the SQL string, or None if there is no table or no usable SQL. Raises LLMError when
    no model is configured (so the orchestrator can degrade honestly)."""
    from teaf import llm

    schema = anomaly.portfolio_schema()
    if not schema["columns"]:
        return None
    try:
        raw = agent.complete_json(
            _sql_system_prompt(schema, anomaly.sample_rows(3)),
            [{"role": "user", "content": query}],
            max_tokens=500,
            schema=_SQL_SCHEMA,
            name="emit_portfolio_sql",
        )
    except llm.LLMError:
        raise
    except Exception:
        return None  # malformed structured output
    return str(raw.get("sql") or "").strip() or None
