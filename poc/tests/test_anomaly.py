"""Tests for the hybrid anomaly pipeline output shape (§6)."""
import config
from teaf.explicit_channels import anomaly


def _write_hybrid_portfolio() -> None:
    """A small controlled portfolio carrying both rule and statistical anomalies."""
    from datetime import date, timedelta

    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    stale = (date.today() - timedelta(days=30 * (anomaly.STALE_MONTHS + 6))).isoformat()
    header = ("app_id,owner,lifecycle_state,business_criticality,technical_maturity,"
              "last_reviewed_date,compliance_status,hosting,annual_cost_chf")
    rows = [header]
    for i in range(1, 41):
        rows.append(f"APP-{i:04d},Owner {i},run,medium,3,{today},compliant,cloud,{50000 + i * 100}")
    rows[5] = f"APP-0005,,run,medium,3,{today},compliant,cloud,52000"               # missing owner
    rows[8] = f"APP-0008,Owner 8,run,medium,3,{today},unknown,cloud,53000"          # compliance unknown
    rows[12] = f"APP-0012,Owner 12,retire,critical,3,{today},compliant,cloud,54000"  # retire + critical
    rows[15] = f"APP-0015,Owner 15,run,medium,3,{stale},compliant,cloud,55000"       # stale review
    rows[20] = f"APP-0020,Owner 20,plan,low,5,{today},compliant,cloud,5000000"       # statistical outlier
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_ensure_portfolio_seeds_default(tmp_env):
    # An empty data dir is seeded from the bundled default portfolio.
    assert anomaly.list_csv_files() == []
    seeded = anomaly.ensure_portfolio()
    assert seeded and seeded[0].name == "portfolio.csv"


def test_detect_payload_is_hybrid(tmp_env):
    _write_hybrid_portfolio()
    payload = anomaly.detect()
    assert set(payload) == {"flagged_records", "summary"}
    s = payload["summary"]
    assert {"total", "rule_flags", "ml_flags", "field_mapping", "skipped_missing_fields"}.issubset(s)
    # hybrid: BOTH a rule source and the ML source produce flags
    assert s["rule_flags"] > 0 and s["ml_flags"] > 0

    sources = {r["source"] for r in payload["flagged_records"]}
    assert sources == {"rule", "isolation_forest"}

    reasons = {r["reason"] for r in payload["flagged_records"]}
    for expected in ("missing_owner", "compliance_unknown", "stale_review", "retire_but_critical"):
        assert expected in reasons

    # rule flags carry null score; ML flags carry a float score + contributions
    for r in payload["flagged_records"]:
        if r["source"] == "rule":
            assert r["score"] is None
        else:
            assert isinstance(r["score"], float)
            assert "feature_contributions" in r


def test_detect_uses_populated_owner_alias(tmp_env, tmp_path):
    path = tmp_path / "uploaded.csv"
    path.write_text(
        "Application ID,Application Owner,Annual Cost\n"
        "APP-0001,Vera Roth,100\n"
        "APP-0002,,200\n"
        "APP-0003,David Steiner,300\n",
        encoding="utf-8",
    )

    payload = anomaly.detect(path)
    missing_owner = [
        r for r in payload["flagged_records"]
        if r["reason"] == "missing_owner"
    ]
    assert payload["summary"]["field_mapping"]["owner"] == "Application Owner"
    assert [r["app_id"] for r in missing_owner] == ["APP-0002"]


def _write_search_csv(tmp_env_dir):
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,vendor,category,annual_cost_chf\n"
        "APP-0001,Acrobat,Adobe,Documents,2000000\n"
        "APP-0002,Photoshop,Adobe,Design,500000\n"
        "APP-0003,DBPlatform,Oracle,Database,3000000\n"
        "APP-0004,SecureConnect,Cisco,VPN,120000\n",
        encoding="utf-8",
    )


def test_run_portfolio_sql_filters_sorts_and_counts(tmp_env):
    _write_search_csv(None)
    # numeric threshold + sort over the FULL typed table
    over = anomaly.run_portfolio_sql(
        "SELECT app_id, vendor, annual_cost_chf FROM portfolio "
        "WHERE annual_cost_chf > 1000000 ORDER BY annual_cost_chf DESC"
    )
    assert over["total"] == 2
    assert [row["app_id"] for row in over["rows"]] == ["APP-0003", "APP-0001"]

    adobe = anomaly.run_portfolio_sql("SELECT app_id FROM portfolio WHERE vendor LIKE '%Adobe%'")
    assert {row["app_id"] for row in adobe["rows"]} == {"APP-0001", "APP-0002"}

    counts = anomaly.run_portfolio_sql("SELECT vendor, COUNT(*) AS n FROM portfolio GROUP BY vendor")
    by_vendor = {row["vendor"]: row["n"] for row in counts["rows"]}
    assert by_vendor["Adobe"] == 2 and by_vendor["Oracle"] == 1 and by_vendor["Cisco"] == 1


def test_run_portfolio_sql_is_read_only(tmp_env):
    _write_search_csv(None)
    import pytest
    for bad in (
        "DROP TABLE portfolio",
        "DELETE FROM portfolio",
        "UPDATE portfolio SET vendor='x'",
        "SELECT * FROM portfolio; DROP TABLE portfolio",
        "PRAGMA query_only = OFF",
    ):
        with pytest.raises(ValueError):
            anomaly.run_portfolio_sql(bad)


def test_sample_rows_and_lookup_by_ids(tmp_env):
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    (config.PORTFOLIO_DIR / "portfolio.csv").write_text(
        "app_id,app_name,owner\n"
        "APP-0180,Acrobat,A. Meier\n"
        "APP-0002,Photoshop,\n"
        "APP-0003,DBPlatform,C. Frei\n"
        "APP-0004,Beacon,D. Haan\n",
        encoding="utf-8",
    )
    sample = anomaly.sample_rows(3)
    assert sample.splitlines()[0] == "app_id,app_name,owner"  # header
    assert "APP-0180" in sample and len(sample.splitlines()) == 4  # header + 3 rows

    rows = anomaly.lookup_rows_by_ids(["APP-0180", "APP-0003"])
    got = {r["app_id"] for r in rows}
    assert got == {"APP-0180", "APP-0003"}
    assert anomaly.lookup_rows_by_ids([]) == []


def test_portfolio_schema_exposes_typed_columns(tmp_env):
    _write_search_csv(None)
    schema = anomaly.portfolio_schema()
    by_name = {c["name"]: c for c in schema["columns"]}
    assert by_name["annual_cost_chf"]["type"] == "NUMERIC"
    assert by_name["vendor"]["type"] == "TEXT"
    assert "Adobe" in by_name["vendor"]["samples"]
    assert schema["row_count"] == 4


def test_detect_skips_owner_rule_when_owner_field_absent(tmp_env, tmp_path):
    path = tmp_path / "uploaded.csv"
    path.write_text(
        "Application ID,Annual Cost\nAPP-0001,100\nAPP-0002,200\n",
        encoding="utf-8",
    )

    payload = anomaly.detect(path)
    assert "owner" in payload["summary"]["skipped_missing_fields"]
    assert not any(r["reason"] == "missing_owner" for r in payload["flagged_records"])
