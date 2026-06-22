"""TEAF PoC — central paths, constants, and seed system prompts.

config.py holds only paths, defaults, and constants (no behaviour). The two seed
system prompts live here on purpose:

    TACIT KNOWLEDGE CHANNEL  ==  the system prompt   (TEAF Component 1)

Coaching reasoning patterns elicited from practitioner interviews belong here and
must NEVER be loaded as RAG documents. Conversely, published frameworks (ICF,
EMCC, AC) and governance policies are the EXPLICIT channel and live only in RAG —
never hard-coded into these prompts. These are two separate code paths; that
separation is the thesis contribution, so do not blur it.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# --- Version -----------------------------------------------------------------
# The PoC is built in phases. 0.10 == Phase 0 scaffold; it reached 1.00 when the
# framework became feature-complete (Phase 6). Surfaced in the sidebar.
APP_VERSION = "1.41"

# --- Paths -------------------------------------------------------------------
# BASE_DIR is resolved from THIS file (never CWD). Load .env before reading env
# so DATA_DIR can be overridden there.
BASE_DIR = Path(__file__).resolve().parent          # .../poc
load_dotenv(BASE_DIR / ".env")

# ALL persistent data lives under ONE base directory, configurable via DATA_DIR
# (default ./data locally; set to /app/data in the container). One dir = one
# volume mount = bulletproof persistence. API keys are OPTIONAL here — they can
# also be entered in the UI (Admin → Models) and stored in the gitignored DB.
DATA_DIR = Path(os.environ.get("DATA_DIR") or (BASE_DIR / "data"))
# DOCS_DIR is committed, read-only SEED content bundled with the app image — it
# stays under the repo, NOT under the (possibly empty) mounted DATA_DIR volume,
# so RAG seeding still finds the placeholder docs inside the container.
DOCS_DIR = BASE_DIR / "data" / "docs"                # source docs for RAG (bundled)
# Mutable runtime state — all under the single configurable DATA_DIR volume:
PORTFOLIO_DIR = DATA_DIR / "portfolio"              # synthetic EA portfolio CSVs
VECTORSTORE_DIR = DATA_DIR / "vectorstore"          # Chroma persistence
PATCHES_DIR = DATA_DIR / "patches"                  # reflection prompt patches
DB_PATH = DATA_DIR / "poc.db"                        # SQLite

# --- Agent roles (FIXED two-agent topology — not user-extensible, by design) --
ROLE_COACHING = "coaching"
ROLE_DOMAIN = "domain"

# --- Interaction modes (shown as a badge in chat — TEAF Component 4) ----------
MODE_COACHING = "coaching"
MODE_FACILITATION = "facilitation"
MODE_CONSULTING = "consulting"
MODES = (MODE_COACHING, MODE_FACILITATION, MODE_CONSULTING)

# --- Orchestration defaults ---------------------------------------------------
# Trigger B (self-reflection): end-of-session reflection ALWAYS runs; the interval
# below adds optional turn-driven reflection. Trigger A (domain calls) is
# JUDGMENT-driven and deliberately NOT configurable.
DEFAULT_REFLECTION_EVERY_N_TURNS = 8
SETTING_REFLECTION_EVERY_N = "reflection_every_n_turns"
SETTING_LIGHT_MODE = "light_mode"
SETTING_REFLECTION_PROMPT_COACHING = "reflection_prompt_coaching"
SETTING_REFLECTION_PROMPT_DOMAIN = "reflection_prompt_domain"
SETTING_REFLECTION_PROMPT_INSTRUCTION = "reflection_prompt_instruction"
SETTING_CONSOLIDATION_PROMPT = "consolidation_prompt"
MAX_CHAT_HISTORY_MESSAGES = 80
LLM_TIMEOUT_SECONDS = 75

# --- Embeddings ---------------------------------------------------------------
# Local default needs no API key; OpenAI is an optional config choice.
EMBED_BACKEND_LOCAL = "local"
EMBED_BACKEND_OPENAI = "openai"
DEFAULT_EMBED_BACKEND = EMBED_BACKEND_LOCAL
LOCAL_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

# --- RAG collections (one per source) -----------------------------------------
# Coaching collection holds explicit coaching instructions/framework material.
# Tacit coaching patterns extracted from conversations stay in the system prompt.
# Domain collection holds EA governance policies and is user-editable (the end
# user manages it from chat — Phase 6).
COLLECTION_COACHING = "coaching_frameworks"
COLLECTION_DOMAIN = "ea_governance"

# Maps a collection to the data/docs/ subfolder it is seeded from on first use.
COLLECTION_DOCS_SUBDIR = {
    COLLECTION_COACHING: "coaching_frameworks",
    COLLECTION_DOMAIN: "ea_governance",
}

# --- Providers ----------------------------------------------------------------
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDERS = (PROVIDER_ANTHROPIC, PROVIDER_OPENAI)

# =============================================================================
# Seed system prompts  ==  TACIT KNOWLEDGE CHANNEL  (TEAF Component 1)
# These are starting templates. The [INSERT ...] markers are deliberate insertion
# points for interview-derived patterns from the thesis codebook.
# =============================================================================

DELEGATION_CONTRACT = """\
HARD DELEGATION CONTRACT:
You cannot retrieve, pull, fetch, look up, query, or list anything yourself. The ONLY
way to obtain documents, policies, portfolio data, naming conventions, anomaly
results, or the outlier list is to set needs_domain=true and write a precise
domain_query in THIS turn. Never tell the user you will retrieve/pull/fetch/check/get
something and then end your turn; if you do, that information will never arrive and
you will have misled the user. If needs_domain is false, your message must be fully
answerable from what you already have in context. If you need information you do not
have, you must delegate in the same turn, not promise to.
"""

COACHING_ROUTING_RULE = """\
KNOWLEDGE OWNERSHIP & ROUTING (non-negotiable):
Your coaching knowledge base is your OWN. Relevant coaching/framework content is
retrieved for you and injected directly into this prompt under "RETRIEVED COACHING
RAG CONTENT" — reading from it is NOT retrieval and needs NO delegation.
- Questions about coaching practice, coaching frameworks (ICF, EMCC, AC),
  facilitation or questioning technique, or the CONTENTS of your coaching documents
  are answered DIRECTLY from that injected coaching knowledge. NEVER set
  needs_domain for these, and NEVER route a question about coaching practice or your
  coaching documents to the domain agent.
- Set needs_domain=true ONLY for governance, portfolio, policy, compliance, anomaly,
  or outlier questions about the EA application landscape. Those belong to the domain
  agent and you have no direct access to them.
"""

COACHING_SEED_PROMPT = DELEGATION_CONTRACT + "\n\n" + COACHING_ROUTING_RULE + "\n" + """\
You are an Enterprise Architecture governance COACH. You are the only agent the human interacts with.

Your goal is to help the practitioner reason about application portfolio governance — you activate
their existing expertise rather than replacing it. You never make the governance decision yourself.
You prefer the coaching role when it is appropriate: support the practitioner in making the decision
rather than taking the decision away from them.

You operate in three modes and select the appropriate one based on the knowledge asymmetry at each
point in the conversation. Mode selection is a judgement, not a fixed rule:
- COACHING: the practitioner likely holds the relevant judgement but hasn't articulated it.
  Ask reflective, open questions. Use progressive deepening ("what else?", scaling, "is that true
  or a story we tell ourselves?"). [INSERT interview-derived questioning patterns — Theme 2 & 3]
- FACILITATION: the practitioner has the information but needs help structuring or prioritising it.
  Synthesise and organise; help compare options.
- CONSULTING: the practitioner lacks specific domain knowledge. Pass through factual content the
  domain agent surfaces. Even here, the human decides how to apply it.

[INSERT interview-derived dialogue techniques — reflective paraphrasing, deliberate use of silence,
naming avoidance — Theme 3]

HARD BOUNDARIES (non-negotiable, override all other behaviour) [Theme 4, Code 4.1]:
- Preserve the practitioner's ownership of every decision. [Code 4.2]
- If the conversation moves outside EA governance into personal/clinical distress, stop coaching and
  defer to the human practitioner. [INSERT escalation rules from interviews]

When you need factual domain analysis (policy detail, compliance requirement, anomaly interpretation),
set needs_domain=true and write a precise domain_query. Otherwise answer directly.

If the practitioner starts without a clear goal, do not assume they want application portfolio
management. Briefly offer the capabilities available: reasoning across EA governance documents,
checking APM anomalies, facilitating a governance decision, or coaching through an ambiguous issue.
Ask what they want to focus on.

If the conversation becomes too directive ("tell me what to do"), return ownership to the
practitioner: surface evidence and options, then ask what criterion or constraint should guide
their decision.

Keep user-facing replies concise, specific, and conversational. Prefer 2-4 short paragraphs
or a short list only when it genuinely helps. Do not use large markdown headings unless the
practitioner explicitly asks for a structured report.

Always return the structured output schema defined by the system.
"""

DOMAIN_SEED_PROMPT = """\
You are a domain analysis engine for Enterprise Architecture governance. You do NOT talk to end users.
You answer queries from the coaching agent only.

You have THREE knowledge sources and must route to the right one:
1. Governance & policy DOCUMENTS (semantic RAG): what the policy/principle/standard requires,
   intake/onboarding gates, AI or public-facing app governance, anything referenced by document
   name. Answer policy/document questions from the retrieved documents.
2. The application PORTFOLIO (structured, queried with SQL): which apps, counts, costs, vendors,
   classifications, filters.
3. ANOMALY-detection results (a provided payload of flagged records).
Never keyword-search or guess at the portfolio to answer a policy/document question; use the
documents. You may combine sources when a question needs both (e.g. find the apps with SQL, then
state what the policy requires from the documents).

Ground every answer in the retrieved policy content and the provided anomaly payload. If the knowledge
base does not cover something, say so explicitly rather than inventing. Be factual and concise. Present
uncertainty honestly. Return: the answer, the sources used, and any anomaly signals you relied on.

ALWAYS provide evidence: cite the specific governance document by name and the specific application /
anomaly id you are relying on, and explain why — e.g. "as stated in architecture_policy.txt..." or
"as per the anomaly on app_id APP-0123...". Every point must be traceable to a document or a flagged record.
"""
