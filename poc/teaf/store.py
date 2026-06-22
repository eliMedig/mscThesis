"""SQLite data access. init_db() is idempotent and seeds the two fixed agents."""
import sqlite3
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import config

# --- Schema ------------------------------------------------------------------
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

CREATE TABLE IF NOT EXISTS process_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    turn       INTEGER NOT NULL,
    step_order INTEGER NOT NULL,
    title      TEXT NOT NULL,
    detail     TEXT,
    status     TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, turn, step_order)
);

CREATE TABLE IF NOT EXISTS governance_tasks (
    id              TEXT PRIMARY KEY,
    app_id          TEXT NOT NULL,
    title           TEXT NOT NULL,
    action          TEXT NOT NULL,
    suggested_owner TEXT NOT NULL,
    source          TEXT NOT NULL,
    reason          TEXT NOT NULL,
    anomaly_score   REAL,
    evidence        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    UNIQUE(app_id, source, reason)
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
        _ensure_prompt_seed_version(c)
        _ensure_reflection_output_version(c)
        _ensure_coaching_delegation_contract(c)
        _ensure_coaching_routing_rule(c)
        _ensure_agent_rag(c)


def _ensure_prompt_seed_version(conn: sqlite3.Connection) -> None:
    # Refreshes managed prompts on a version bump; a later hand-edit survives until the
    # next bump. Stored reflection prompts are cleared so they cannot shadow new defaults.
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (config.SETTING_PROMPT_SEED_VERSION,)
    ).fetchone()
    if row is not None and row["value"] == config.PROMPT_SEED_VERSION:
        return
    for role, prompt in (
        (config.ROLE_COACHING, config.COACHING_SEED_PROMPT),
        (config.ROLE_DOMAIN, config.DOMAIN_SEED_PROMPT),
    ):
        conn.execute("UPDATE agents SET system_prompt = ? WHERE role = ?", (prompt, role))
    # Clear stored reflection-prompt overrides so the editor shows the new code defaults.
    conn.execute(
        "DELETE FROM app_settings WHERE key IN (?, ?, ?, ?)",
        (
            config.SETTING_REFLECTION_PROMPT_COACHING,
            config.SETTING_REFLECTION_PROMPT_DOMAIN,
            config.SETTING_REFLECTION_PROMPT_INSTRUCTION,
            config.SETTING_CONSOLIDATION_PROMPT,
        ),
    )
    conn.execute(
        "INSERT INTO app_settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (config.SETTING_PROMPT_SEED_VERSION, config.PROMPT_SEED_VERSION),
    )


def _ensure_reflection_output_version(conn: sqlite3.Connection) -> None:
    # Refreshes only the shared output instruction, leaving the role prompts intact.
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (config.SETTING_REFLECTION_OUTPUT_VERSION,),
    ).fetchone()
    if row is not None and row["value"] == config.REFLECTION_OUTPUT_VERSION:
        return
    conn.execute(
        "DELETE FROM app_settings WHERE key = ?",
        (config.SETTING_REFLECTION_PROMPT_INSTRUCTION,),
    )
    conn.execute(
        "INSERT INTO app_settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (config.SETTING_REFLECTION_OUTPUT_VERSION, config.REFLECTION_OUTPUT_VERSION),
    )


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
    # Migrates the routing rule into older Coaching Agent prompts, idempotent on the heading.
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
    # Runs on every init so an older DB migrates in place rather than being wiped.
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
    # Idempotent so re-approving a patch does not duplicate its text.
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
    # Reverses append_to_system_prompt when an approved patch is later rejected.
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


# --- observable process trace -------------------------------------------------
def add_process_step(session_id: int, turn: int, title: str, detail: str | None = None,
                     status: str = "completed") -> int:
    """Append one observed orchestration event to a turn's audit trace."""
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(step_order), 0) AS n FROM process_steps "
            "WHERE session_id = ? AND turn = ?",
            (session_id, turn),
        ).fetchone()
        step_order = int(row["n"]) + 1
        cur = c.execute(
            "INSERT INTO process_steps(session_id, turn, step_order, title, detail, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (session_id, turn, step_order, title, detail, status, _now()),
        )
        return cur.lastrowid


def list_process_steps(session_id: int, turn: int | None = None) -> list[sqlite3.Row]:
    with _conn() as c:
        if turn is not None:
            return c.execute(
                "SELECT * FROM process_steps WHERE session_id = ? AND turn = ? "
                "ORDER BY step_order, id",
                (session_id, turn),
            ).fetchall()
        return c.execute(
            "SELECT * FROM process_steps WHERE session_id = ? ORDER BY turn, step_order, id",
            (session_id,),
        ).fetchall()


# --- governance task queue ----------------------------------------------------
TASK_STATUSES = ("pending", "approved", "rejected")


def create_governance_tasks(tasks: list[dict]) -> int:
    # UNIQUE(app_id, source, reason) is the dedup guard; UUIDs assigned only here so the
    # task transformation stays pure and deterministic.
    if not tasks:
        return 0
    inserted = 0
    with _conn() as c:
        for task in tasks:
            cur = c.execute(
                "INSERT OR IGNORE INTO governance_tasks("
                "id, app_id, title, action, suggested_owner, source, reason, "
                "anomaly_score, evidence, status, created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,'pending',?)",
                (
                    str(uuid.uuid4()),
                    str(task["app_id"]),
                    str(task["title"]),
                    str(task["action"]),
                    str(task["suggested_owner"]),
                    str(task["source"]),
                    str(task["reason"]),
                    task.get("anomaly_score"),
                    json.dumps(task.get("evidence") or {}, sort_keys=True, default=str),
                    _now(),
                ),
            )
            inserted += int(cur.rowcount > 0)
    return inserted


def list_governance_tasks(status: str | None = None) -> list[sqlite3.Row]:
    with _conn() as c:
        if status is not None:
            return c.execute(
                "SELECT * FROM governance_tasks WHERE status = ? "
                "ORDER BY suggested_owner COLLATE NOCASE, created_at, app_id",
                (status,),
            ).fetchall()
        return c.execute(
            "SELECT * FROM governance_tasks "
            "ORDER BY status, suggested_owner COLLATE NOCASE, created_at, app_id"
        ).fetchall()


def count_governance_tasks(status: str | None = None) -> int:
    with _conn() as c:
        if status is None:
            row = c.execute("SELECT COUNT(*) AS n FROM governance_tasks").fetchone()
        else:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM governance_tasks WHERE status = ?", (status,)
            ).fetchone()
        return int(row["n"])


def update_governance_task_status(task_id: str, status: str) -> None:
    if status not in TASK_STATUSES:
        raise ValueError(f"Unknown governance task status: {status}")
    with _conn() as c:
        c.execute("UPDATE governance_tasks SET status = ? WHERE id = ?", (status, task_id))


def update_governance_task_owner(task_id: str, suggested_owner: str) -> None:
    owner = str(suggested_owner or "").strip()
    if not owner:
        raise ValueError("Suggested owner cannot be blank.")
    with _conn() as c:
        c.execute(
            "UPDATE governance_tasks SET suggested_owner = ? WHERE id = ?", (owner, task_id)
        )


def delete_governance_task(task_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM governance_tasks WHERE id = ?", (task_id,))


def clear_governance_tasks() -> None:
    with _conn() as c:
        c.execute("DELETE FROM governance_tasks")


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


def count_patches(status: str | None = None) -> int:
    with _conn() as c:
        if status is None:
            row = c.execute("SELECT COUNT(*) AS n FROM prompt_patches").fetchone()
        else:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM prompt_patches WHERE status = ?", (status,)
            ).fetchone()
        return int(row["n"])


def list_patches_for_agent(agent_id: int, status: str) -> list[sqlite3.Row]:
    """Patches for one agent in a given status (used by per-agent consolidation)."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM prompt_patches WHERE agent_id = ? AND status = ? "
            "ORDER BY created_at DESC",
            (agent_id, status),
        ).fetchall()


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
        c.execute("DELETE FROM process_steps")
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM sessions")


def clear_patches() -> None:
    """Delete all prompt patches (the Tacit Externalisation records)."""
    with _conn() as c:
        c.execute("DELETE FROM prompt_patches")


def clear_all_user_data() -> None:
    # Wipes user data but keeps configuration: registered models and the two agents.
    with _conn() as c:
        c.execute("DELETE FROM governance_tasks")
        c.execute("DELETE FROM process_steps")
        c.execute("DELETE FROM messages")
        c.execute("DELETE FROM sessions")
        c.execute("DELETE FROM prompt_patches")
        c.execute("DELETE FROM app_settings")
