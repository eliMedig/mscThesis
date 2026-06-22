"""Governance task generation and persistence tests."""
import json
import uuid

import pandas as pd

import config
from teaf import llm, store
from teaf.explicit_channels import anomaly


def _sample_payload():
    return {
        "flagged_records": [
            {
                "app_id": "APP-0001", "reason": "stale_review", "source": "rule",
                "score": None,
            },
            {
                "app_id": "APP-0002", "reason": "missing_owner", "source": "rule",
                "score": None,
            },
            {
                "app_id": "APP-0001", "reason": "statistical_outlier",
                "source": "isolation_forest", "score": -0.1234,
                "feature_contributions": {"technical_maturity": 5, "annual_cost": 5000000},
            },
        ],
        "summary": {},
    }


def _sample_df():
    return pd.DataFrame([
        {
            "app_id": "APP-0001", "owner": "Architecture Team",
            "last_reviewed_date": "2022-01-01",
        },
        {
            "app_id": "APP-0002", "owner": "",
            "last_reviewed_date": "2026-01-01",
        },
    ])


def test_task_mapping_is_deterministic_and_resolves_owners():
    first = anomaly.build_governance_tasks(_sample_payload(), _sample_df())
    second = anomaly.build_governance_tasks(_sample_payload(), _sample_df())
    assert first == second
    assert len(first) == 3

    by_reason = {task["reason"]: task for task in first}
    stale = by_reason["stale_review"]
    assert stale["title"] == "Review overdue"
    assert stale["action"] == "Conduct a governance review of APP-0001."
    assert stale["suggested_owner"] == "Architecture Team"
    assert stale["evidence"] == {"last_reviewed_date": "2022-01-01"}

    missing = by_reason["missing_owner"]
    assert missing["suggested_owner"] == config.GOVERNANCE_TASK_FALLBACK_OWNER
    assert missing["action"] == "Assign an application owner to APP-0002."

    outlier = by_reason["statistical_outlier"]
    assert outlier["anomaly_score"] == -0.1234
    assert outlier["evidence"]["annual_cost"] == 5000000


def test_detection_creates_tasks_without_llm_and_deduplicates(tmp_env, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Governance task generation must not call an LLM")

    monkeypatch.setattr(llm, "chat", forbidden)
    monkeypatch.setattr(llm, "chat_json", forbidden)
    path = tmp_path / "portfolio.csv"
    rows = [
        "app_id,owner,lifecycle_state,business_criticality,technical_maturity,"
        "last_reviewed_date,compliance_status,hosting,annual_cost"
    ]
    for i in range(1, 31):
        owner = "" if i == 2 else f"Owner {i}"
        rows.append(
            f"APP-{i:04d},{owner},run,medium,3,2026-01-01,compliant,hybrid,{1000 + i}"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    payload = anomaly.detect(path)
    unique_flags = {
        (flag["app_id"], flag["source"], flag["reason"])
        for flag in payload["flagged_records"]
    }
    assert store.count_governance_tasks() == len(unique_flags)
    missing = next(
        task for task in store.list_governance_tasks()
        if task["app_id"] == "APP-0002" and task["reason"] == "missing_owner"
    )
    assert missing["suggested_owner"] == config.GOVERNANCE_TASK_FALLBACK_OWNER
    uuid.UUID(missing["id"])

    store.update_governance_task_status(missing["id"], "approved")
    anomaly.detect(path)
    assert store.count_governance_tasks() == len(unique_flags)
    preserved = next(task for task in store.list_governance_tasks() if task["id"] == missing["id"])
    assert preserved["status"] == "approved"


def test_task_transitions_reassignment_and_deletion(tmp_env):
    tasks = anomaly.build_governance_tasks(_sample_payload(), _sample_df())
    assert store.create_governance_tasks(tasks) == 3
    assert store.create_governance_tasks(tasks) == 0

    saved = store.list_governance_tasks()
    first, second = saved[0], saved[1]
    store.update_governance_task_owner(first["id"], "Risk Team")
    store.update_governance_task_status(first["id"], "approved")
    store.update_governance_task_status(second["id"], "rejected")

    approved = store.list_governance_tasks("approved")
    rejected = store.list_governance_tasks("rejected")
    assert len(approved) == 1 and approved[0]["suggested_owner"] == "Risk Team"
    assert len(rejected) == 1
    assert json.loads(approved[0]["evidence"])

    third = next(task for task in saved if task["id"] not in {first["id"], second["id"]})
    store.delete_governance_task(third["id"])
    assert store.count_governance_tasks() == 2
    store.clear_governance_tasks()
    assert store.count_governance_tasks() == 0


def test_clear_all_user_data_includes_tasks(tmp_env):
    store.create_governance_tasks(anomaly.build_governance_tasks(_sample_payload(), _sample_df()))
    assert store.count_governance_tasks() == 3
    store.clear_all_user_data()
    assert store.count_governance_tasks() == 0
