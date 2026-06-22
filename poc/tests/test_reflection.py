"""Tests for per-agent pending-patch consolidation (Trigger B externalisation)."""
import config
from teaf import llm, reflection, store


def _make_pending(agent_id: int, n: int) -> list[int]:
    ids = []
    for i in range(n):
        body = (
            f"# Prompt Patch - session 1\n\nTarget agent: coaching\n\n"
            f"## Insight\nInsight {i}\n"
            f"## Suggested system-prompt addition\nAlways ask one focused question (variant {i}).\n"
            f"## Rationale\nKeeps ownership with the practitioner.\n"
        )
        ids.append(store.add_patch(1, agent_id, body))
    return ids


def test_consolidation_merges_and_supersedes(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    coaching = store.get_agent_by_role(config.ROLE_COACHING)
    store.update_agent(coaching["id"], reflection_model_id=model_id)
    store.create_session()

    source_ids = _make_pending(coaching["id"], 3)

    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        captured["user"] = messages[0]["content"]
        return (
            "## Insight\nMerged insight.\n"
            "## Suggested system-prompt addition\nAsk one focused question before offering frameworks.\n"
            "## Rationale\nDe-duplicated from three near-identical captures.\n"
        )

    monkeypatch.setattr(llm, "chat", fake_chat)

    result = reflection.consolidate_pending_patches(coaching["id"])

    assert result["created"] is not None
    assert sorted(result["consolidated_ids"]) == sorted(source_ids)
    # All sources are retained but moved off the pending list.
    assert store.list_patches_for_agent(coaching["id"], "pending") and \
        all(p["id"] not in source_ids for p in store.list_patches_for_agent(coaching["id"], "pending"))
    assert {p["id"] for p in store.list_patches_for_agent(coaching["id"], "consolidated")} == set(source_ids)
    # The consolidation prompt and every source patch reached the model.
    assert "single de-duplicated patch" in captured["system"]
    for sid in source_ids:
        assert f"#{sid}" in captured["user"]


def test_consolidation_needs_two(tmp_env):
    coaching = store.get_agent_by_role(config.ROLE_COACHING)
    store.create_session()
    _make_pending(coaching["id"], 1)
    result = reflection.consolidate_pending_patches(coaching["id"])
    assert result["created"] is None
    assert "at least two" in result["message"].lower()
