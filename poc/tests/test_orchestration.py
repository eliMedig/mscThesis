"""Tests for the orchestration loop with fake agents, so no API key or network is needed."""
import config
from teaf import llm, orchestration, store
from teaf.agents import coaching_agent, domain_agent
from teaf.agents.base import Agent
from teaf.explicit_channels import anomaly, rag


def test_domain_call_branch(tmp_env, monkeypatch):
    # Coach judges it needs domain analysis and supplies a query.
    monkeypatch.setattr(coaching_agent, "decide", lambda hist: {
        "mode": config.MODE_CONSULTING, "needs_domain": True,
        "domain_query": "what is the review cadence?", "message": None,
    })
    # Domain agent returns grounded findings (no real RAG/LLM).
    monkeypatch.setattr(domain_agent, "answer", lambda q, **k: {
        "answer": "Reviewed at least every 12 months.",
        "sources": ["architecture_policy.txt"], "anomaly_used": False,
    })
    monkeypatch.setattr(coaching_agent, "finalize",
                        lambda hist, q, res, mode: f"[{mode}] On review timing: {res['answer']}")
    monkeypatch.setattr(anomaly, "get_payload", lambda *a, **k: None)

    sid = store.create_session()
    out = orchestration.handle_user_turn(sid, "How often should we review apps?")

    assert out["used_domain"] is True
    assert out["mode"] == config.MODE_CONSULTING
    roles = [m["role"] for m in store.list_messages(sid)]
    assert roles == ["user", "domain", "coaching"]
    coach = [m for m in store.list_messages(sid) if m["role"] == "coaching"][0]
    assert coach["mode"] == config.MODE_CONSULTING
    assert coach["content"].startswith("[consulting]")
    steps = store.list_process_steps(sid, 1)
    titles = [step["title"] for step in steps]
    assert titles[0] == "User input received"
    assert "Domain Agent consultation started" in titles
    assert "Domain Agent returned its analysis" in titles
    assert "Domain findings passed to the Coaching Agent" in titles
    assert "Coaching Agent composed the final response" in titles
    assert "Response returned" in titles
    domain_step = next(step for step in steps if step["title"] == "Domain Agent returned its analysis")
    assert "Reviewed at least every 12 months." in domain_step["detail"]
    assert "architecture_policy.txt" in domain_step["detail"]
    assert [step["step_order"] for step in steps] == list(range(1, len(steps) + 1))


def test_no_domain_branch(tmp_env, monkeypatch):
    monkeypatch.setattr(coaching_agent, "decide", lambda hist: {
        "mode": config.MODE_COACHING, "needs_domain": False,
        "domain_query": None, "message": "What does your own judgement say?",
    })
    sid = store.create_session()
    out = orchestration.handle_user_turn(sid, "I think we should retire it")
    assert out["used_domain"] is False
    assert [m["role"] for m in store.list_messages(sid)] == ["user", "coaching"]
    assert out["message"] == "What does your own judgement say?"
    steps = store.list_process_steps(sid, 1)
    titles = [step["title"] for step in steps]
    assert "Domain Agent not consulted" in titles
    assert "Domain Agent consultation started" not in titles
    assert titles[-1] == "Turn-based reflection not triggered"


def test_domain_unavailable_degrades(tmp_env, monkeypatch):
    monkeypatch.setattr(coaching_agent, "decide", lambda hist: {
        "mode": config.MODE_FACILITATION, "needs_domain": True,
        "domain_query": "policy?", "message": None,
    })
    monkeypatch.setattr(anomaly, "get_payload", lambda *a, **k: None)

    def boom(q, **k):
        raise RuntimeError("no model")

    monkeypatch.setattr(domain_agent, "answer", boom)
    sid = store.create_session()
    out = orchestration.handle_user_turn(sid, "policy question")
    assert out["used_domain"] is False
    roles = [m["role"] for m in store.list_messages(sid)]
    assert "system" in roles and roles[-1] == "coaching"
    assert "will not pretend" in out["message"]


def test_coach_lookup_promise_auto_delegates(tmp_env, monkeypatch):
    captured = {}

    def fake_complete_json(self, system, messages, max_tokens=0, schema=None, name=""):
        captured["schema"] = schema
        captured["name"] = name
        return {
            "mode": config.MODE_CONSULTING,
            "needs_domain": False,
            "domain_query": None,
            "message": "I'll pull the naming-convention rules from your governance documents.",
        }

    monkeypatch.setattr(Agent, "complete_json", fake_complete_json)

    out = coaching_agent.decide([
        {"role": "user", "content": "Can you list the naming conventions?"}
    ])

    assert captured["name"] == "emit_coaching_decision"
    assert captured["schema"]["required"] == ["mode", "needs_domain", "domain_query", "message"]
    assert out["needs_domain"] is True
    assert out["domain_query"] == "Can you list the naming conventions?"
    assert out["message"] is None
    assert out["contract_violation"] == "retrieval_intent_without_delegation"


def test_requires_domain_routing():
    # Coaching-practice / coaching-document questions must NOT force-delegate.
    assert coaching_agent._requires_domain("what's in your coaching documents?") is False
    assert coaching_agent._requires_domain("what does the ICF framework say about powerful questions?") is False
    assert coaching_agent._requires_domain("help me coach this governance discussion") is False
    # Governance / portfolio / anomaly questions still delegate.
    assert coaching_agent._requires_domain("what does the architecture policy say about ownership?") is True
    assert coaching_agent._requires_domain("list the isolation-forest outliers") is True
    assert coaching_agent._requires_domain("show me the raw record for app APP-0001") is True
    assert coaching_agent._requires_domain("which applications are non_compliant?") is True
    # numeric/sort/count portfolio queries must delegate too
    assert coaching_agent._requires_domain("apps with annual cost over 1 million") is True
    assert coaching_agent._requires_domain("count apps by vendor") is True
    assert coaching_agent._requires_domain("any Adobe apps") is True


def test_coaching_agent_uses_only_coaching_rag(tmp_env, monkeypatch):
    calls = []
    captured = {}

    def fake_ensure_seeded(collection):
        calls.append(collection)
        return 0

    def fake_retrieve(collection, query, k=3):
        return [{
            "text": "Use one focused coaching question before offering frameworks.",
            "source": "coaching_style.txt",
        }]

    def fake_complete_json(self, system, messages, max_tokens=0, schema=None, name=""):
        captured["system"] = system
        return {
            "mode": config.MODE_COACHING,
            "needs_domain": False,
            "domain_query": None,
            "message": "What would make this useful right now?",
        }

    monkeypatch.setattr(rag, "ensure_seeded", fake_ensure_seeded)
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(Agent, "complete_json", fake_complete_json)

    out = coaching_agent.decide([
        {"role": "user", "content": "Help me coach this governance discussion."}
    ])

    assert out["needs_domain"] is False
    assert config.COLLECTION_COACHING in calls
    assert config.COLLECTION_DOMAIN not in calls
    assert "Use one focused coaching question" in captured["system"]


def test_domain_agent_gets_rag_and_anomaly_payload(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)

    monkeypatch.setattr(rag, "ensure_seeded", lambda collection: 0)
    monkeypatch.setattr(rag, "retrieve", lambda collection, query, k=4: [{
        "text": "Application IDs follow APP-NNNN naming.",
        "source": "naming_conventions.txt",
    }])

    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "Grounded answer."

    monkeypatch.setattr(llm, "chat", fake_chat)
    payload = {"flagged_records": [{"app_id": "APP-0001", "reason": "statistical_outlier"}]}

    out = domain_agent.answer("What are the naming conventions?", anomaly_payload=payload)

    assert "Grounded answer." in out["answer"]
    assert out["sources"] == ["naming_conventions.txt"]
    assert "Application IDs follow APP-NNNN naming." in captured["system"]
    assert "ACTIVE ANOMALY PAYLOAD" in captured["system"]
    assert "APP-0001" in captured["system"]


def test_anomaly_question_consolidates_payload_rows_and_rag(tmp_env, monkeypatch):
    # An anomaly question fuses the payload + the flagged apps' REAL portfolio rows
    # (the data the detector ran on) + governance RAG.
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,owner\nAPP-0001,Atlas,\nAPP-0002,Beacon,B. Schmidt\n", encoding="utf-8",
    )
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: (
        [{"text": "Every application must have a named owner.", "source": "architecture_policy.txt"}], [],
    ))
    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "APP-0001 (Atlas) is flagged missing_owner and has no owner."

    monkeypatch.setattr(llm, "chat", fake_chat)
    payload = {"flagged_records": [
        {"app_id": "APP-0001", "reason": "missing_owner", "source": "rule", "score": None},
    ]}

    out = domain_agent.answer("list the flagged outliers", anomaly_payload=payload)

    assert "ACTIVE ANOMALY PAYLOAD" in captured["system"]
    assert "FLAGGED APPLICATIONS" in captured["system"]
    assert "Atlas" in captured["system"]  # the flagged app's real portfolio row was pulled in
    assert "architecture_policy.txt" in out["sources"]
    assert out["anomaly_used"] is True


def test_app_query_consolidates_sql_schema_and_loose_id(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,vendor,annual_cost_chf\n"
        "APP-0180,Acrobat,Adobe,2000000\nAPP-0002,Photoshop,Adobe,500000\n",
        encoding="utf-8",
    )
    captured = {}

    def fake_complete_json(self, system, messages, max_tokens=0, schema=None, name=""):
        captured["sql_system"] = system
        captured["name"] = name
        # loose-id lookup: 'app 180' → match the real APP-0180 via LIKE
        return {"sql": "SELECT app_id, vendor, annual_cost_chf FROM portfolio WHERE app_id LIKE '%180%'"}

    monkeypatch.setattr(Agent, "complete_json", fake_complete_json)
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: (
        [{"text": "policy text", "source": "architecture_policy.txt"}], [],
    ))

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "Here is everything on APP-0180."

    monkeypatch.setattr(llm, "chat", fake_chat)

    out = domain_agent.answer("give me all you have on app 180", anomaly_payload=None)

    # SQL prompt is schema-grounded: shows the real id format (APP-0180) + CHF note
    assert captured["name"] == "emit_portfolio_sql"
    assert "APP-0180" in captured["sql_system"] and "CHF" in captured["sql_system"]
    # consolidation: the SQL result rows + policy RAG reach the synthesis
    assert "PORTFOLIO QUERY RESULT" in captured["system"] and "APP-0180" in captured["system"]
    assert "RETRIEVED POLICY CONTENT" in captured["system"]
    assert "Portfolio query used:" in out["answer"]
    assert "architecture_policy.txt" in out["sources"]


def test_domain_sql_failure_is_surfaced_not_crashed(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text("app_id,vendor\nAPP-0001,Adobe\n", encoding="utf-8")
    monkeypatch.setattr(
        Agent, "complete_json",
        lambda self, system, messages, max_tokens=0, schema=None, name="": {"sql": "DROP TABLE portfolio"},
    )
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: ([], []))
    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "I could not query the portfolio."

    monkeypatch.setattr(llm, "chat", fake_chat)

    domain_agent.answer("list all apps", anomaly_payload=None)
    # a non-SELECT is rejected and surfaced as a failed-query note (not opening rows, not a crash)
    assert "portfolio query failed" in captured["system"].lower()


def test_domain_routing_classifiers():
    da = domain_agent
    # governance/policy/document questions → policy (RAG)
    assert da._is_policy_question("What does our EA governance require for onboarding a new application?")
    assert da._is_policy_question("Summarise EntArch.pdf's requirements for AI or public-facing apps.")
    assert da._is_policy_question("which Confidential apps are non-compliant and what does policy require")
    # portfolio-data questions are NOT policy
    assert not da._is_policy_question("how many apps are non-compliant?")
    assert not da._is_policy_question("list all Adobe apps")
    # data detector still catches data questions, not pure policy ones
    assert da._is_portfolio_search_query("how many apps are non-compliant?")
    assert not da._is_portfolio_search_query("what does our EA governance require for onboarding?")


def test_policy_question_uses_rag_not_sql(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: (
        [{"text": "Onboarding requires an intake review and a named owner.",
          "source": "architecture_policy.txt"}], [],
    ))
    sql_calls = {"n": 0}

    def maybe_sql(self, system, messages, max_tokens=0, schema=None, name=""):
        sql_calls["n"] += 1
        return {"sql": "SELECT 1"}

    monkeypatch.setattr(Agent, "complete_json", maybe_sql)
    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "Onboarding needs an intake review."

    monkeypatch.setattr(llm, "chat", fake_chat)

    out = domain_agent.answer(
        "What does our EA governance require for onboarding a new application?", anomaly_payload=None
    )
    assert sql_calls["n"] == 0  # a policy question must NOT generate portfolio SQL
    assert "architecture_policy.txt" in out["sources"]
    assert "Onboarding needs an intake review." in out["answer"]
    assert "RETRIEVED POLICY CONTENT" in captured["system"]
    assert "Retrieved from governance documents" in out["answer"]  # routing visible


def test_combined_question_uses_sql_and_rag(tmp_env, monkeypatch):
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,data_classification,compliance_status\n"
        "APP-0001,Endur,Confidential,non_compliant\n"
        "APP-0002,Atlas,Public,compliant\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        Agent, "complete_json",
        lambda self, system, messages, max_tokens=0, schema=None, name="": {
            "sql": ("SELECT app_id, data_classification, compliance_status FROM portfolio "
                    "WHERE data_classification='Confidential' AND compliance_status='non_compliant'")
        },
    )
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: (
        [{"text": "Confidential applications must be compliant before go-live.",
          "source": "compliance_rules.txt"}], [],
    ))
    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "APP-0001 is Confidential and non-compliant; policy requires compliance before go-live."

    monkeypatch.setattr(llm, "chat", fake_chat)

    out = domain_agent.answer(
        "Which Confidential apps are non-compliant, and what does policy require for them?",
        anomaly_payload=None,
    )
    assert "PORTFOLIO QUERY RESULT" in captured["system"]
    assert "RETRIEVED POLICY CONTENT" in captured["system"]
    assert "APP-0001" in captured["system"]  # SQL rows injected
    assert "compliance_rules.txt" in out["sources"]
    assert "Portfolio query used:" in out["answer"]


def test_why_flagged_consolidates_row_payload_and_policy(tmp_env, monkeypatch):
    # "why is APP-0001 flagged?" fuses the app's real row (real column business_owner) +
    # the anomaly payload + governance RAG into one synthesis.
    model_id = store.add_model("fake", config.PROVIDER_OPENAI, "fake-model", "fake-key")
    domain = store.get_agent_by_role(config.ROLE_DOMAIN)
    store.update_agent(domain["id"], model_id=model_id)
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,business_owner\nAPP-0001,Openlink Endur,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        Agent, "complete_json",
        lambda self, system, messages, max_tokens=0, schema=None, name="": {
            "sql": "SELECT app_id, app_name, business_owner FROM portfolio WHERE app_id LIKE '%0001%'"
        },
    )
    monkeypatch.setattr(rag, "retrieve_for_agent", lambda agent_id, query, k=4: (
        [{"text": "Every application must have a named owner.", "source": "architecture_policy.txt"}], [],
    ))
    captured = {}

    def fake_chat(provider, model_string, api_key, system, messages, max_tokens=llm.DEFAULT_MAX_TOKENS):
        captured["system"] = system
        return "APP-0001 has no owner; flagged missing_owner; violates the ownership rule."

    monkeypatch.setattr(llm, "chat", fake_chat)
    payload = {"flagged_records": [
        {"app_id": "APP-0001", "reason": "missing_owner", "source": "rule", "score": None},
    ]}

    out = domain_agent.answer("why is APP-0001 flagged?", anomaly_payload=payload)

    assert "Openlink Endur" in captured["system"]            # the real row (SQL + flagged-rows)
    assert "ACTIVE ANOMALY PAYLOAD" in captured["system"]    # the anomaly result
    assert "Every application must have a named owner." in captured["system"]  # policy RAG
    assert out["anomaly_used"] is True
    assert "active_anomaly_payload" in out["sources"]
