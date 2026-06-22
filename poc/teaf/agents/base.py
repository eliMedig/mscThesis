"""This defines the agent class"""
from __future__ import annotations
import sqlite3
from teaf import llm, models, store


class Agent:
    def __init__(self, row: sqlite3.Row):
        self.row = row
        self.id = row["id"]
        self.role = row["role"]
        self.name = row["name"]
        self.system_prompt = row["system_prompt"]

    @classmethod
    def load(cls, role: str) -> "Agent | None":
        row = store.get_agent_by_role(role)
        return cls(row) if row else None

    def model(self) -> sqlite3.Row | None:
        return models.resolve_for_agent(self.row)

    def complete_json(self, system: str, messages: list[dict],
                      max_tokens: int = llm.DEFAULT_MAX_TOKENS,
                      schema: dict | None = None,
                      name: str = "structured_output") -> dict:
        # system overrides the stored prompt so the caller can append the output schema.
        m = self._require_model()
        return llm.chat_json(m["provider"], m["model_string"], m["api_key"],
                             system, messages, max_tokens, schema=schema, name=name)

    def _require_model(self) -> sqlite3.Row:
        m = self.model()
        if m is None:
            raise llm.LLMError(
                f"The {self.name} has no model assigned. Assign one in Settings → Agents."
            )
        return m
