"""Model registry logic — thin layer over the ``models`` table.

A model is (name, provider, model_string, api_key). The api_key may be NULL, in
which case the provider key is read from the environment (poc/.env). Registered
models are assigned to agents on the Agents admin page.
"""
from __future__ import annotations

import sqlite3

from teaf import store


def resolve_for_agent(agent_row: sqlite3.Row | None) -> sqlite3.Row | None:
    """Return the ``models`` row assigned to an agent, or None if unassigned."""
    if agent_row is None or agent_row["model_id"] is None:
        return None
    return store.get_model(agent_row["model_id"])


def resolve_reflection_for_agent(agent_row: sqlite3.Row | None) -> sqlite3.Row | None:
    """Return the model row used for reflection, falling back to conversation model."""
    if agent_row is None:
        return None
    try:
        reflection_model_id = agent_row["reflection_model_id"]
    except (KeyError, IndexError):
        reflection_model_id = None
    if reflection_model_id is not None:
        return store.get_model(reflection_model_id)
    return resolve_for_agent(agent_row)


def label(model_row: sqlite3.Row) -> str:
    """Human label for a model, e.g. 'Claude Sonnet (prod) · anthropic/claude-sonnet-4-6'."""
    return f"{model_row['name']} · {model_row['provider']}/{model_row['model_string']}"


def masked_key(api_key: str | None) -> str:
    """Mask a key for display — only the last 4 chars survive."""
    if not api_key:
        return "— from .env —"
    return "••••" + api_key[-4:] if len(api_key) > 4 else "••••"
