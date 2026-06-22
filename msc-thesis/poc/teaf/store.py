"""SQLite DAO for the TEAF PoC.

A single module owns the schema and every database access. Tables mirror §4 of the
build spec. ``init_db()`` is idempotent: it creates tables when missing and seeds
the FIXED two-agent topology (one coaching, one domain) on first run.

Persistence is intentionally simple (plain SQLite, no ORM) — this is a PoC whose
job is to make the TEAF components legible to a thesis examiner, not to scale.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import config

# --- Schema (all seven tables from §4) ---------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    provider     TEXT NOT NULL,        -- 'anthropic' | 'openai'
    model_string TEXT NOT NULL,        -- e.g. 'claude-sonnet-4-6'
    api_key      TEXT,                 -- NULL means read from env
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    role           TEXT NOT NULL,      -- 'coaching' | 'domain' (fixed set)
    name           TEXT NOT NULL,
    model_id       INTEGER REFERENCES models(id) ON DELETE SET NULL,
    reflection_model_id INTEGER REFERENCES models(id) ON DELETE SET NULL,
    system_prompt  TEXT NOT NULL,
    user_visible_kb INTEGER NOT NULL DEFAULT 0,
    active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS agent_rag (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    collection_name TEXT NOT NULL,
    user_editable   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    status     TEXT NOT NULL           -- 'active' | 'ended'
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn       INTEGER NOT NULL,
    role       TEXT NOT NULL,          -- 'user' | 'coaching' | 'domain' | 'system'
    mode       TEXT,                   -- coaching mode, for 'coaching' turns
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_patches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id   INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,          -- the structured patch (markdown)
    status     TEXT NOT NULL,          -- 'pending' | 'approved' | 'rejected' | 'consolidated' (retained, off the pending list)
    created_at TEXT NOT NULL,
    decided_at TEXT
);

-- Not in §4: a tiny key/value store for interaction-trigger config (Trigger B).
CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    """Open a connection with Row access and FK enforcement on."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _conn():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Initialisation + seed ----------------------------------------------------
def init_db() -> None:
    """Create tables if missing and seed the two agents. Safe to call every run."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(SCHEMA)
        _migrate_schema(c)
        _seed_agents(c)
        _ensure_coaching_delegation_contract(c)
        _ensure_coaching_routing_rule(c)
        _ensure_agent_rag(c)


def _migrate_schema(conn: sqlite3.Connection) -> None:
    agent_cols = {r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
    if "reflection_model_id" not in agent_cols:
        conn.execute("ALTER TABLE agents ADD COLUMN reflection_model_id INTEGER REFERENCES models(id) ON DELETE SET NULL")


def _seed_agents(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) AS n FROM agents").fetchone()["n"] > 0:
        return
    conn.execute(
        "INSERT INTO agents(role, name, model_id, system_prompt, user_visible_kb, active) "
        "VALUES (?,?,?,?,?,?)",
        (config.ROLE_COACHING, "Coaching Agent", None, config.COACHING_SEED_PROMPT, 0, 1),
    )
    # The Domain Agent's KB is user-visible/editable: the end user manages it from chat.
    conn.execute(
        "INSERT INTO agents(role, name, model_id, system_prompt, user_visible_kb, active) "
        "VALUES (?,?,?,?,?,?)",
        (config.ROLE_DOMAIN, "Domain Agent", None, config.DOMAIN_SEED_PROMPT, 1, 1),
    )


def _ensure_coaching_delegation_contract(conn: sqlite3.Connection) -> None:
    """Prepend the hard delegation contract to existing Coaching Agent prompts."""
    row = conn.execute(
        "SELECT id, system_prompt FROM agents WHERE role = ?", (config.ROLE_COACHING,)
    ).fetchone()
    if row is None:
        return
    prompt = row["system_prompt"] or ""
    if "HARD DELEGATION CONTRACT:" in prompt:
        return
    conn.execute(
        "UPDATE agents SET system_prompt = ? WHERE id = ?",
        (config.DELEGATION_CONTRACT.strip() + "\n\n" + prompt, row["id"]),
    )


def _ensure_coaching_routing_rule(conn: sqlite3.Connection) -> None:
    """Inject the knowledge-ownership/routing rule into existing Coaching Agent
    prompts so the coach answers coaching questions from its own RAG and only
    delegates governance/portfolio questions. Idempotent (keyed on the heading)."""
    row = conn.execute(
        "SELECT id, system_prompt FROM agents WHERE role = ?", (config.ROLE_COACHING,)
    ).fetchone()
    if row is None:
        return
    prompt = row["system_prompt"] or ""
    if "KNOWLEDGE OWNERSHIP & ROUTING" in prompt:
        return
    rule = config.COACHING_ROUTING_RULE.strip()
    # Place the rule right after the delegation contract when present, else prepend.
    marker = config.DELEGATION_CONTRACT.strip()
    if marker and marker in prompt:
        updated = prompt.replace(marker, marker + "\n\n" + rule, 1)
    else:
        updated = rule + "\n\n" + prompt
    conn.execute(
        "UPDATE agents SET system_prompt = ? WHERE id = ?", (updated, row["id"])
    )


def _ensure_agent_rag(conn: sqlite3.Connection) -> None:
    """Idempotently attach each agent's default RAG collection.

    Runs on every init so an existing DB (seeded before collections existed)
    migrates in place rather than being wiped. Both collections are user-editable
    from Data Sources, but each remains attached only to its owning agent.
    """
    defaults = {
        config.ROLE_COACHING: (config.COLLECTION_COACHING, 1),
        config.ROLE_DOMAIN: (config.COLLECTION_DOMAIN, 1),
    }
    for role, (collection, editable) in defaults.items():
        agent = conn.execute("SELECT id FROM agents WHERE role = ?", (role,)).fetchone()
        if agent is None:
            continue
        exists = conn.execute(
            "SELECT 1 FROM agent_rag WHERE agent_id = ? AND collection_name = ?",
            (agent["id"], collection),
        ).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO agent_rag(agent_id, collection_name, user_editable) VALUES (?,?,?)",
                (agent["id"], collection, editable),
            )
        else:
            conn.execute(
                "UPDATE agent_rag SET user_editable = ? WHERE agent_id = ? AND collection_name = ?",
                (editable, agent["id"], collection),
            )


# --- models -------------------------------------------------------------------
def add_model(name: str, provider: str, model_string: str, api_key: str | None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO models(name, provider, model_string, api_key, created_at) "
            "VALUES (?,?,?,?,?)",
            (name, provider, model_string, api_key or None, _now()),
        )
        return cur.lastrowid


def list_models() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM models ORDER BY created_at DESC").fetchall()


def get_model(model_id: int) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM models WHERE id = ?", (model_id,)).fetchone()


def delete_model(model_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM models WHERE id = ?", (model_id,))


# Sentinel: leave the api_key unchanged on update.
KEEP_KEY = object()


def update_model(model_id, name, provider, model_string, api_key=KEEP_KEY) -> None:
    """Edit a registered model. Pass api_key=KEEP_KEY to leave the stored key as-is,
    None/'' to clear it (fall back to env), or a string to replace it."""
    with _conn() as c:
        if api_key is KEEP_KEY:
            c.execute(
                "UPDATE models SET name=?, provider=?, model_string=? WHERE id=?",
                (name, provider, model_string, model_id),
            )
        else:
            c.execute(
                "UPDATE models SET name=?, provider=?, model_string=?, api_key=? WHERE id=?",
                (name, provider, model_string, (api_key or None), model_id),
            )


# --- agents -------------------------------------------------------------------
def list_agents() -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute("SELECT * FROM agents ORDER BY id").fetchall()


def get_agent(agent_id: int) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()


def get_agent_by_role(role: str) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM agents WHERE role = ?", (role,)).fetchone()


def update_agent(agent_id: int, **fields) -> None:
    """Update a whitelisted set of agent columns."""
    allowed = {"model_id", "reflection_model_id", "system_prompt", "user_visible_kb", "active", "name"}
    cols = {k: v for k, v in fields.items() if k in allowed}
    if not cols:
        return
    assignments = ", ".join(f"{k} = ?" for k in cols)
    with _conn() as c:
        c.execute(f"UPDATE agents SET {assignments} WHERE id = ?", (*cols.values(), agent_id))


def _patch_block(addition: str) -> str:
    return "\n\n" + addition.strip() + "\n"


def append_to_system_prompt(agent_id: int, addition: str) -> None:
    """Append approved patch text to an agent's system prompt (§9). Idempotent —
    does nothing if the text is already present (so re-approving won't duplicate)."""
    with _conn() as c:
        row = c.execute("SELECT system_prompt FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None:
            return
        prompt = row["system_prompt"] or ""
        if addition.strip() and addition.strip() in prompt:
            return
        c.execute("UPDATE agents SET system_prompt = ? WHERE id = ?",
                  (prompt + _patch_block(addition), agent_id))


def remove_from_system_prompt(agent_id: int, addition: str) -> None:
    """Reverse append_to_system_prompt — used when an approved patch is later
    rejected. Removes the appended block (or the bare text) if present."""
    with _conn() as c:
        row = c.execute("SELECT system_prompt FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None or not addition.strip():
            return
        prompt = row["system_prompt"] or ""
        block = _patch_block(addition)
        if block in prompt:
            prompt = prompt.replace(block, "")
        elif addition.strip() in prompt:
            prompt = prompt.replace(addition.strip(), "")
        else:
            return
        c.execute("UPDATE agents SET system_prompt = ? WHERE id = ?", (prompt, agent_id))


# --- agent_rag ----------------------------------------------------------------
def add_agent_rag(agent_id: int, collection_name: str, user_editable: bool) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO agent_rag(agent_id, collection_name, user_editable) VALUES (?,?,?)",
            (agent_id, collection_name, int(user_editable)),
        )
        return cur.lastrowid


def list_agent_rag(agent_id: int) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM agent_rag WHERE agent_id = ? ORDER BY id", (agent_id,)
        ).fetchall()


def list_agent_rag_by_role(role: str) -> list[sqlite3.Row]:
    """Collections attached to a role, used to render separated Data Sources."""
    with _conn() as c:
        agent = c.execute("SELECT id FROM agents WHERE role = ?", (role,)).fetchone()
        if agent is None:
            return []
        return c.execute(
            "SELECT * FROM agent_rag WHERE agent_id = ? ORDER BY collection_name",
            (agent["id"],),
        ).fetchall()


def delete_agent_rag(rag_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM agent_rag WHERE id = ?", (rag_id,))


def list_user_editable_collections() -> list[sqlite3.Row]:
    """Collections the end user may browse/add to from chat (user_editable = 1)."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM agent_rag WHERE user_editable = 1 ORDER BY collection_name"
        ).fetchall()


# --- sessions -----------------------------------------------------------------
def create_session() -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO sessions(started_at, ended_at, status) VALUES (?,?,?)",
            (_now(), None, "active"),
        )
        return cur.lastrowid


def end_session(session_id: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET ended_at = ?, status = 'ended' WHERE id = ?",
            (_now(), session_id),
        )


def get_session(session_id: int) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def get_active_session() -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()


# --- messages -----------------------------------------------------------------
def add_message(session_id: int, turn: int, role: str, content: str, mode: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO messages(session_id, turn, role, mode, content, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (session_id, turn, role, mode, content, _now()),
        )
        return cur.lastrowid


def list_messages(session_id: int) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY turn, id", (session_id,)
        ).fetchall()


def max_turn(session_id: int) -> int:
    with _conn() as c:
        row = c.execute(
            "SELECT MAX(turn) AS t FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row["t"] or 0


# --- prompt_patches -----------------------------------------------------------
def add_patch(session_id: int, agent_id: int, content: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO prompt_patches(session_id, agent_id, content, status, created_at) "
            "VALUES (?,?,?, 'pending', ?)",
            (session_id, agent_id, content, _now()),
        )
        return cur.lastrowid


def list_patches(status: str | None = None) -> list[sqlite3.Row]:
    with _conn() as c:
        if status:
            return c.execute(
                "SELECT * FROM prompt_patches WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        return c.execute("SELECT * FROM prompt_patches ORDER BY created_at DESC").fetchall()


def list_patches_for_agent(agent_id: int, status: str) -> list[sqlite3.Row]:
    """Patches for one agent in a given status (used by per-agent consolidation)."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM prompt_patches WHERE agent_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            (agent_id, status),
        ).fetchall()


def get_patch(patch_id: int) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM prompt_patches WHERE id = ?", (patch_id,)).fetchone()


def set_patch_status(patch_id: int, status: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE prompt_patches SET status = ?, decided_at = ? WHERE id = ?",
            (status, _now(), patch_id),
        )


# --- app_settings (interaction-trigger config) --------------------------------
def get_setting(key: str, default: str | None = None) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO app_settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


# --- danger zone (test resets) ------------------------------------------------
def clear_conversations() -> None:
    """Delete all sessions + messages (keeps models, agents, patches, settings)."""
    with _conn() as c:
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM sessions")


def clear_patches() -> None:
    """Delete all prompt patches (the Tacit Externalisation records)."""
    with _conn() as c:
        c.execute("DELETE FROM prompt_patches")


def clear_all_user_data() -> None:
    """Wipe USER data (conversations, patches, settings) — keeps configuration
    (registered models and the two agents)."""
    with _conn() as c:
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM prompt_patches")
        c.execute("DELETE FROM app_settings")
