# TEAF Proof of Concept

Proof of concept for an MSc Artificial Intelligence thesis introducing the
**Tacit Externalisation Framework (TEAF)** — a two-agent system that maps
knowledge-management theory onto AI agent design for **Enterprise Architecture (EA)
governance coaching**.

This is a **PoC, not a product**. Its only job is to make the four TEAF components
*visible and demonstrable* to an examiner. It is optimised for clarity and
traceability to the framework — **not** for scale, generality, security, or
production-readiness.

> **Status:** feature-complete — **v1.41** (all six build phases done; see
> [Build phases](#build-phases)).

---

## The four TEAF components

1. **Explicit Knowledge Channels** — RAG (static documented knowledge) + anomaly
   detection (dynamic data-driven knowledge) + externalised system prompts
   (codified tacit knowledge).
2. **Coaching Agent** — the only agent the human talks to. Manages the
   conversation, switches interaction mode, orchestrates the domain agent, and runs
   self-reflection.
3. **Domain Agent** — background only. Synthesises domain answers from RAG + anomaly
   signals. Never talks to the human directly.
4. **Knowledge Interface** — the UI. Bidirectional exchange; makes the agent's
   current interaction mode visible to the user.

### The hard architectural rule (the thesis contribution)

Two knowledge channels, **two separate code paths** — never blurred:

| Channel | Lives in | Holds |
|---|---|---|
| **Tacit** | the **system prompt** (`config.py` → `teaf/store.py`) | coaching reasoning patterns elicited from practitioner interviews |
| **Explicit** | **RAG** (`teaf/explicit_channels/rag.py`) | published frameworks (ICF, EMCC, AC) + governance policies |

Interview-derived patterns are **never** loaded as RAG documents; published
frameworks are **never** hard-coded into a prompt.

---

## TEAF → module mapping

This table is the traceability deliverable; it stays aligned with the code as the
build progresses.

| TEAF element | Module(s) | Notes |
|---|---|---|
| **Component 1 — Explicit Channels: RAG** | `teaf/explicit_channels/rag.py` | one Chroma collection per source; accepts `.txt`/`.md`/`.pdf` uploads (text-based PDFs via pypdf; scanned/image PDFs skipped, no OCR); `retrieve_for_agent` restricts each agent to its own linked collection(s) — coaching ↔ coaching frameworks, domain ↔ EA policies (hard channel isolation, enforced in code) |
| **Component 1 — Explicit Channels: anomaly detection** | `teaf/explicit_channels/anomaly.py` | hybrid: rule-based checks + Isolation Forest over synthetic EA portfolio |
| **Component 1 — Explicit Channels: structured portfolio query** | `teaf/explicit_channels/anomaly.py` (`portfolio_schema` / `run_portfolio_sql`) | the portfolio is STRUCTURED data, not RAG: loaded into a typed in-memory SQLite table; the Domain Agent writes ONE read-only `SELECT` (numeric thresholds, `ORDER BY`, `LIKE`, `GROUP BY`) run via a SELECT-only tool, then joins anomaly flags by `app_id` |
| **Component 1 — Explicit Channels: codified tacit knowledge** | `config.py` (seed prompts) + `teaf/store.py` (`agents.system_prompt`) | tacit channel = the system prompt |
| **Component 2 — Coaching Agent** | `teaf/agents/coaching_agent.py` | the only agent the human talks to; mode selection + domain signalling + reflection |
| **Component 3 — Domain Agent** | `teaf/agents/domain_agent.py` | background only; routes across THREE sources — governance-document RAG (policy/principle/standard/document questions), portfolio SQL (data questions), anomaly payload — and may combine them; never keyword-searches the portfolio for a policy question |
| **Component 4 — Knowledge Interface** | `app.py`, `ui/chat.py`, `ui/admin_*.py` | chat + mode badge + user-managed domain KB + admin |
| Orchestration (two triggers) | `teaf/orchestration.py` | Trigger A judgment-driven domain calls; Trigger B turn-driven reflection |
| Self-reflection → prompt patch | `teaf/reflection.py`, `ui/admin_patches.py` | human-approved; never auto-applied |
| Model registry | `teaf/models.py`, `teaf/llm.py`, `ui/admin_models.py` | provider-agnostic (Anthropic + OpenAI) |
| Persistence | `teaf/store.py` | SQLite; all tables per §4 |

---

## Setup

Requires **Python 3.11+** (developed on 3.12). From the **repository root**:

```powershell
# 1. Create + activate a virtualenv inside poc/
py -3.12 -m venv poc/.venv
poc/.venv/Scripts/Activate.ps1

# 2. Install dependencies
pip install -r poc/requirements.txt

# 3. (optional) provide API keys — you can also enter them in the UI later
copy poc/.env.example poc/.env   # then edit poc/.env
```

> RAG uses a **local** embedding model by default, so the app runs with **no API
> key**. Keys are only needed once you assign an LLM to an agent (Phase 1+).

## Run

```powershell
streamlit run poc/app.py
```

The app opens with a **Chat** page (Knowledge Interface) and a **Settings** page
whose tabs cover Models, Agents, Interaction triggers, Tacit Externalisation, and a
Danger zone. On first run it creates `poc/data/poc.db` and seeds the two agents.

## Tests

```powershell
cd poc
pytest
```

---

## Deliberate design choices

- **Tacit vs explicit channel separation.** The tacit channel is the system prompt;
  the explicit channel is RAG. They are separate code paths and never mixed — this
  separation *is* the framework contribution, so the code enforces it rather than
  leaving it to convention.
- **Hybrid anomaly detection.** Some governance anomalies are statistical outliers
  (Isolation Forest); others are data-quality rule violations a pure ML model can't
  catch (e.g. missing owner, `retire` + `critical`). Both feed one payload. The LLM
  interprets the payload — it never computes anomalies.
- **Judgment-driven vs turn-driven triggers.** Domain calls (Trigger A) are decided
  per turn by the Coaching Agent via structured output — a knowledge-informed act,
  not a turn counter. Self-reflection (Trigger B) is the turn-driven one. Only
  Trigger B is configurable; making Trigger A a knob would reduce it to a mechanical
  relay, which the framework rejects.
- **Human-approved patches.** Self-reflection externalises a structured prompt patch
  to disk and records it as `pending`. A human approves it in admin before it is
  appended to a system prompt. Nothing is auto-merged — the agent externalises, the
  human governs what persists.
- **Single process, two fixed agents.** No microservices, no "add any agent" UI, no
  inter-agent rules engine, no cross-session auto-memory — all explicitly out of
  scope (mirrors Section 5.1 of the thesis).

---

## Build phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Scaffold: structure, SQLite schema + DAO, Streamlit shell, seeded agents, README | ✅ done (v0.10) |
| 1 | LLM wrapper + model registry + single-agent chat | ✅ done (v0.20) |
| 2 | Domain agent + two-call orchestration + RAG | ✅ done (v0.30) |
| 3 | Mode selection + mode badge + user correction | ✅ done (v0.40) |
| 4 | Synthetic data + hybrid anomaly pipeline | ✅ done (v0.50) |
| 5 | Reflection + prompt patches + admin review | ✅ done (v0.60) |
| 6 | User-managed domain KB + polish + tests | ✅ done (v1.00) |

## Project layout

```
poc/
  app.py                 # Streamlit entrypoint + page routing (Component 4 shell)
  config.py              # paths, constants, seed system prompts (tacit channel)
  teaf/
    store.py             # SQLite DAO (all tables)
    models.py            # model registry logic
    llm.py               # provider-agnostic chat() wrapper
    explicit_channels/
      rag.py             # RAG ingest/retrieve  (Component 1, static)
      anomaly.py         # hybrid anomaly pipeline (Component 1, dynamic)
    agents/
      base.py            # shared agent abstraction
      coaching_agent.py  # Component 2
      domain_agent.py    # Component 3
    orchestration.py     # turn loop + both triggers
    reflection.py        # transcript -> prompt patch
  ui/
    chat.py              # Component 4: chat + mode badge + domain-KB browse/add
    admin_models.py      # model + API key registry
    admin_agents.py      # per-agent config
    admin_interaction.py # trigger config
    admin_patches.py     # review/approve/reject patches
  tests/                 # orchestration / anomaly / rag
```
