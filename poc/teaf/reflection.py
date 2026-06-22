"""Self-reflection -> prompt patches.

Reflection externalises proposed improvements for both agents, but a human still
governs what persists. Each generated patch targets one agent and approving it
appends only that patch's suggested addition to the target agent's system prompt.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import config
from teaf import llm, store
from teaf import models as model_registry
from teaf.agents.base import Agent

_SUGGESTED_HEADING = "## Suggested system-prompt addition"
_TS_FORMAT = "%Y%m%dT%H%M%SZ"  # patch filename / header timestamp

_COACHING_REFLECTION_SYSTEM = (
    "You are the Coaching Agent reflecting on a completed Enterprise Architecture "
    "governance coaching session in order to improve your own FUTURE coaching "
    "behaviour. Identify "
    "governance-relevant reasoning or interaction insights that emerged this session "
    "and would make the coach more effective next time, such as a questioning pattern "
    "that worked, a mode-selection cue, or a boundary to respect. Be concrete and "
    "conservative."
)

_DOMAIN_REFLECTION_SYSTEM = (
    "You are the Coaching Agent reflecting on the same completed coaching session, "
    "but this pass targets the Domain Agent's FUTURE behaviour. Identify "
    "domain-analysis insights that would make the domain agent more accurate, grounded, "
    "or useful next time, such as evidence standards, policy interpretation cues, "
    "anomaly interpretation patterns, or retrieval guidance. Be concrete and conservative."
)

_REFLECTION_INSTRUCTION = (
    "Output EXACTLY these three markdown sections and nothing else:\n"
    "## Insight\n<what was learned this session>\n"
    "## Suggested system-prompt addition\n<the concrete text to append to the target "
    "agent's system prompt - a few sentences, ready to paste, no preamble. If there is "
    "no useful target-specific addition, write exactly NO_CHANGE>\n"
    "## Rationale\n<why this addition helps, or why no change is needed>\n"
)

_CONSOLIDATION_SYSTEM = (
    "You are given several pending reflection patches for the same agent. Some capture "
    "the same or overlapping insight, because reflection ran repeatedly during one "
    "conversation. Merge them into a single de-duplicated patch that preserves every "
    "distinct insight and its suggested system-prompt addition, removing repetition and "
    "near-duplicates. Output one consolidated patch in the standard patch format."
)


def default_reflection_prompts() -> dict[str, str]:
    """Default editable prompts for the reflection/externalisation workflow."""
    return {
        config.SETTING_REFLECTION_PROMPT_COACHING: _COACHING_REFLECTION_SYSTEM,
        config.SETTING_REFLECTION_PROMPT_DOMAIN: _DOMAIN_REFLECTION_SYSTEM,
        config.SETTING_REFLECTION_PROMPT_INSTRUCTION: _REFLECTION_INSTRUCTION,
    }


def get_reflection_prompt(role: str) -> str:
    if role == config.ROLE_DOMAIN:
        key = config.SETTING_REFLECTION_PROMPT_DOMAIN
    else:
        key = config.SETTING_REFLECTION_PROMPT_COACHING
    return str(store.get_setting(key, default_reflection_prompts()[key]))


def get_reflection_instruction() -> str:
    key = config.SETTING_REFLECTION_PROMPT_INSTRUCTION
    return str(store.get_setting(key, default_reflection_prompts()[key]))


def default_consolidation_prompt() -> str:
    """Default editable prompt for per-agent pending-patch consolidation."""
    return _CONSOLIDATION_SYSTEM


def get_consolidation_prompt() -> str:
    return str(store.get_setting(config.SETTING_CONSOLIDATION_PROMPT, _CONSOLIDATION_SYSTEM))


def build_transcript(session_id: int) -> str:
    lines = []
    for m in store.list_messages(session_id):
        if m["role"] == "user":
            lines.append(f"PRACTITIONER: {m['content']}")
        elif m["role"] == "coaching":
            lines.append(f"COACH[{m['mode'] or '-'}]: {m['content']}")
        elif m["role"] == "domain":
            lines.append(f"DOMAIN_BACKGROUND: {m['content']}")
    return "\n".join(lines)


def reflect_on_session(session_id: int) -> list[dict]:
    """Generate pending prompt patches for the coaching and domain agents."""
    transcript = build_transcript(session_id)
    if not transcript.strip():
        return []

    created = []
    for role in (config.ROLE_COACHING, config.ROLE_DOMAIN):
        try:
            patch = _reflect_for_agent(session_id, role, transcript)
        except Exception:
            patch = None
        if patch:
            created.append(patch)
    return created


def consolidate_pending_patches(agent_id: int) -> dict:
    """Merge all PENDING patches for one agent into a single consolidated pending patch.

    The source patches are marked 'consolidated' (retained for audit, removed from the
    pending list — never hard-deleted). The new patch uses the standard 3-section format
    and enters the normal pending → approve/reject flow. Returns a status dict:
      {"created": <patch dict>|None, "consolidated_ids": [...], "message": str}
    """
    pending = store.list_patches_for_agent(agent_id, "pending")
    if len(pending) < 2:
        return {"created": None, "consolidated_ids": [], "message": "Need at least two pending patches to consolidate."}

    agent = store.get_agent(agent_id)
    if agent is None:
        return {"created": None, "consolidated_ids": [], "message": "Unknown agent."}

    reflection_owner = Agent.load(config.ROLE_COACHING)
    m = model_registry.resolve_reflection_for_agent(reflection_owner.row) if reflection_owner else None
    if m is None:
        return {"created": None, "consolidated_ids": [],
                "message": "No reflection model assigned. Set one in Settings → Agents."}

    # Oldest-first so the merge reads in the order the insights were captured.
    ordered = list(reversed(pending))
    source_ids = [p["id"] for p in ordered]
    blocks = "\n\n".join(f"--- Patch #{p['id']} ---\n{p['content']}" for p in ordered)
    system = get_consolidation_prompt() + "\n\n" + get_reflection_instruction()
    body = llm.chat(
        m["provider"], m["model_string"], m["api_key"], system,
        [{"role": "user", "content": f"Target agent: {agent['name']}\n\nPending patches to consolidate:\n\n{blocks}"}],
        max_tokens=1600,
    )

    session_id = max(p["session_id"] for p in ordered)
    md = _build_consolidated_markdown(session_id, agent["role"], source_ids, body)
    addition = extract_suggested_addition(md)
    if not addition or addition.strip().upper() == "NO_CHANGE":
        return {"created": None, "consolidated_ids": [],
                "message": "Consolidation produced no usable addition; pending patches left unchanged."}

    ts = datetime.now(timezone.utc).strftime(_TS_FORMAT)
    folder = config.PATCHES_DIR / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{ts}_{agent['role']}_consolidated.md").write_text(md, encoding="utf-8")

    patch_id = store.add_patch(session_id, agent_id, md)
    for sid in source_ids:
        store.set_patch_status(sid, "consolidated")  # retained for audit, off the pending list
    return {
        "created": {"patch_id": patch_id, "content": md, "role": agent["role"]},
        "consolidated_ids": source_ids,
        "message": f"Consolidated {len(source_ids)} pending patches into patch #{patch_id}.",
    }


def _build_consolidated_markdown(session_id: int, role: str, source_ids: list[int], body: str) -> str:
    ts = datetime.now(timezone.utc).strftime(_TS_FORMAT)
    sources = ", ".join(f"#{i}" for i in source_ids)
    return (
        f"# Consolidated Prompt Patch - session {session_id} - {ts}\n\n"
        f"Target agent: {role}\n\n"
        f"Consolidated from patches: {sources}\n\n"
        f"{body.strip()}\n"
    )


def _reflect_for_agent(session_id: int, role: str, transcript: str) -> dict | None:
    agent = Agent.load(role)
    if agent is None:
        return None

    reflection_owner = Agent.load(config.ROLE_COACHING)
    if reflection_owner is None:
        return None
    m = model_registry.resolve_reflection_for_agent(reflection_owner.row)
    if m is None:
        return None
    system = get_reflection_prompt(role)
    instruction = get_reflection_instruction()
    body = llm.chat(
        m["provider"],
        m["model_string"],
        m["api_key"],
        system + "\n\n" + instruction,
        [{"role": "user", "content": f"Target agent: {agent.name}\n\nSession transcript:\n\n{transcript}"}],
        max_tokens=1200,
    )

    md = _build_patch_markdown(session_id, role, body)
    addition = extract_suggested_addition(md)
    if not addition or addition.strip().upper() == "NO_CHANGE":
        return None

    ts = datetime.now(timezone.utc).strftime(_TS_FORMAT)
    folder = config.PATCHES_DIR / str(session_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{ts}_{role}.md"
    path.write_text(md, encoding="utf-8")

    patch_id = store.add_patch(session_id, agent.id, md)
    return {"patch_id": patch_id, "path": str(path), "content": md, "role": role}


def _build_patch_markdown(session_id: int, role: str, body: str) -> str:
    ts = datetime.now(timezone.utc).strftime(_TS_FORMAT)
    return f"# Prompt Patch - session {session_id} - {ts}\n\nTarget agent: {role}\n\n{body.strip()}\n"


def extract_suggested_addition(markdown: str) -> str:
    """Return the text under '## Suggested system-prompt addition'."""
    pattern = re.compile(
        re.escape(_SUGGESTED_HEADING) + r"\s*(.*?)(?:\n##\s|\Z)", re.DOTALL
    )
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""
