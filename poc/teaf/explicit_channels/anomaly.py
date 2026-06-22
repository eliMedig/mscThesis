# This component is documented and explained in the thesis. The comments here
# cover technical detail that may not be in the thesis.
from __future__ import annotations

import re
import shutil
from datetime import date

import config
from teaf import store

# Ordinal order for the Isolation Forest encoding and the rule-check vocabulary.
LIFECYCLE = ["plan", "build", "run", "retire"]
CRITICALITY = ["low", "medium", "high", "critical"]
COMPLIANCE = ["compliant", "non_compliant", "unknown"]
HOSTING = ["on_prem", "cloud", "hybrid"]

CSV_NAME = "portfolio.csv"
STALE_MONTHS = 18

# Standard portfolio bundled with the app, seeded into the data dir on first run.
DEFAULT_PORTFOLIO = config.BASE_DIR / "data" / "portfolio" / CSV_NAME

_TASK_COPY = {
    "missing_owner": (
        "Missing owner",
        "Assign an application owner to {app_id}.",
        ("owner",),
    ),
    "compliance_unknown": (
        "Compliance status unknown",
        "Reconcile the compliance status for {app_id}.",
        ("compliance_status",),
    ),
    "stale_review": (
        "Review overdue",
        "Conduct a governance review of {app_id}.",
        ("last_reviewed_date",),
    ),
    "invalid_review_date": (
        "Invalid review date",
        "Correct the governance review date for {app_id}.",
        ("last_reviewed_date",),
    ),
    "retire_but_critical": (
        "Lifecycle/criticality conflict",
        "Review {app_id}: retired but business-critical.",
        ("lifecycle_state", "business_criticality"),
    ),
    "statistical_outlier": (
        "Statistical anomaly",
        "Investigate {app_id}: flagged as a statistical outlier.",
        (),
    ),
}

_payload_cache: dict | None = None

STANDARD_FIELDS = (
    "app_id",
    "app_name",
    "owner",
    "lifecycle_state",
    "business_criticality",
    "technical_maturity",
    "last_reviewed_date",
    "compliance_status",
    "hosting",
    "annual_cost",
)

_COLUMN_CANDIDATES = {
    "app_id": ("app_id", "application_id", "applicationid", "appid", "id"),
    "app_name": ("app_name", "application_name", "application", "name", "system_name"),
    "owner": (
        "owner",
        "application_owner",
        "app_owner",
        "business_owner",
        "technical_owner",
        "owner_name",
        "responsible_owner",
        "accountable_owner",
        "service_owner",
        "product_owner",
    ),
    "lifecycle_state": ("lifecycle_state", "lifecycle", "life_cycle", "state", "phase", "status"),
    "business_criticality": (
        "business_criticality",
        "criticality",
        "business_impact",
        "impact",
        "criticality_rating",
    ),
    "technical_maturity": ("technical_maturity", "tech_maturity", "maturity", "technology_maturity"),
    "last_reviewed_date": (
        "last_reviewed_date",
        "last_review_date",
        "last_review",
        "review_date",
        "reviewed_on",
        "assessment_date",
    ),
    "compliance_status": ("compliance_status", "compliance", "audit_status", "policy_status"),
    "hosting": ("hosting", "hosting_model", "deployment", "deployment_model", "platform"),
    "annual_cost": ("annual_cost_chf", "annual_cost", "yearly_cost", "annual_run_cost", "run_cost", "total_cost", "cost"),
}


def portfolio_path():
    return config.PORTFOLIO_DIR / CSV_NAME


def list_csv_files():
    if not config.PORTFOLIO_DIR.is_dir():
        return []
    return sorted(config.PORTFOLIO_DIR.glob("*.csv"))


def ensure_portfolio():
    # Seed the bundled default into the data dir on first run (empty mounted volume).
    if list_csv_files():
        return list_csv_files()
    if DEFAULT_PORTFOLIO.exists() and DEFAULT_PORTFOLIO.resolve() != portfolio_path().resolve():
        config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DEFAULT_PORTFOLIO, portfolio_path())
    return list_csv_files()


def list_datasets() -> list[dict]:
    """The current data scope: each CSV file feeding detection, with row counts."""
    out = []
    for f in list_csv_files():
        try:
            with open(f, encoding="utf-8") as fh:
                rows = max(0, sum(1 for _ in fh) - 1)  # minus header
        except OSError:
            rows = 0
        out.append({"name": f.name, "rows": rows})
    return out


def _safe_name(name: str) -> str:
    base = (name or "upload.csv").replace("\\", "/").split("/")[-1].strip()
    if not base.lower().endswith(".csv"):
        base += ".csv"
    return base


def add_dataset(name: str, data: bytes) -> str:
    """Add an uploaded CSV to the active data scope. Returns the stored filename."""
    config.PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    fname = _safe_name(name)
    (config.PORTFOLIO_DIR / fname).write_bytes(data)
    return fname


def remove_dataset(name: str) -> None:
    f = config.PORTFOLIO_DIR / _safe_name(name)
    if f.exists():
        f.unlink()


def read_dataset(name: str) -> bytes:
    """Return the raw bytes of a dataset CSV (for download)."""
    f = config.PORTFOLIO_DIR / _safe_name(name)
    return f.read_bytes() if f.exists() else b""


# --- structured SQL query tool over the full portfolio (not semantic RAG) -------
# Structured data needs a real query engine for thresholds, sorts, and column filters,
# so the table loads into an in-memory SQLite DB exposed as a read-only SELECT tool.
_SQL_MAX_ROWS = 200


def portfolio_schema() -> dict:
    # Sample values for low-cardinality text columns help the agent write correct filters.
    df = _combined_df()
    columns = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        is_numeric = dtype.startswith(("int", "float", "uint"))
        samples: list[str] = []
        if not is_numeric:
            uniq = df[col].dropna().astype(str).unique().tolist()
            samples = sorted(uniq)[:25] if len(uniq) <= 25 else [str(v) for v in uniq[:6]]
        columns.append({"name": str(col), "type": "NUMERIC" if is_numeric else "TEXT", "samples": samples})
    return {"table": "portfolio", "row_count": int(len(df)), "columns": columns}


def sample_rows(n: int = 3) -> str:
    # Shows the agent the exact id format and value spellings, not just column names.
    df = _combined_df()
    if df.empty:
        return "(no portfolio data)"
    return df.head(n).to_csv(index=False).strip()


def _detect_id_column(df) -> str | None:
    norm = {_normalise_col(c): c for c in df.columns}
    for candidate in ("app_id", "application_id", "applicationid", "appid", "id"):
        if candidate in norm:
            return norm[candidate]
    return None


def lookup_rows_by_ids(app_ids, limit: int = 25) -> list[dict]:
    # Full rows for flagged apps let the domain agent explain what is wrong, not just that.
    df = _combined_df()
    if df.empty or not app_ids:
        return []
    id_col = _detect_id_column(df)
    if id_col is None:
        return []
    wanted = {str(x) for x in app_ids if x is not None}
    matches = df[df[id_col].astype(str).isin(wanted)].head(limit)
    return matches.to_dict("records")


def _build_portfolio_db():
    import sqlite3

    df = _combined_df()
    conn = sqlite3.connect(":memory:")
    if not df.empty:
        df.to_sql("portfolio", conn, index=False, if_exists="replace")
    conn.execute("PRAGMA query_only = ON")  # engine-level read-only guard
    return conn


_FORBIDDEN_SQL = (
    "insert", "update", "delete", "drop", "alter", "create", "attach", "detach",
    "pragma", "vacuum", "reindex", "truncate", "grant", "revoke",
)


def _validate_select(sql: str) -> str:
    """Accept exactly one read-only SELECT (or WITH…SELECT); reject everything else."""
    cleaned = (sql or "").strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("Empty SQL statement.")
    if ";" in cleaned:
        raise ValueError("Only a single statement is allowed.")
    low = cleaned.lower()
    if not low.startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed.")
    for kw in _FORBIDDEN_SQL:
        if re.search(rf"\b{kw}\b", low):
            raise ValueError(f"Statement type not allowed: {kw}.")
    return cleaned


def run_portfolio_sql(sql: str, max_rows: int = _SQL_MAX_ROWS) -> dict:
    # SELECT-only is enforced three ways: single statement, SELECT/WITH prefix, query_only.
    safe = _validate_select(sql)
    conn = _build_portfolio_db()
    try:
        cur = conn.execute(safe)
        names = [d[0] for d in cur.description]
        fetched = cur.fetchall()
    finally:
        conn.close()
    total = len(fetched)
    rows = [
        {n: ("" if v is None else v) for n, v in zip(names, row)}
        for row in fetched[:max_rows]
    ]
    return {
        "sql": safe,
        "columns": names,
        "rows": rows,
        "total": total,
        "truncated": total > len(rows),
    }


# --- detection ----------------------------------------------------------------
def _rule(app_id, reason):
    return {"app_id": app_id, "reason": reason, "source": "rule", "score": None}


def _rule_checks(df, today, synthetic_columns: set[str] | None = None) -> list[dict]:
    # One row may raise several flags.
    synthetic_columns = synthetic_columns or set()
    flags: list[dict] = []
    for _, row in df.iterrows():
        app = row["app_id"]
        if "owner" not in synthetic_columns and not str(row["owner"]).strip():
            flags.append(_rule(app, "missing_owner"))
        if (
            "compliance_status" not in synthetic_columns
            and str(row["compliance_status"]).strip() in ("", "unknown")
        ):
            flags.append(_rule(app, "compliance_unknown"))
        if "last_reviewed_date" not in synthetic_columns:
            try:
                reviewed = date.fromisoformat(str(row["last_reviewed_date"]))
                if (today - reviewed).days > STALE_MONTHS * 30:
                    flags.append(_rule(app, "stale_review"))
            except ValueError:
                flags.append(_rule(app, "invalid_review_date"))
        if (
            "lifecycle_state" not in synthetic_columns
            and "business_criticality" not in synthetic_columns
            and row["lifecycle_state"] == "retire"
            and row["business_criticality"] == "critical"
        ):
            flags.append(_rule(app, "retire_but_critical"))
    return flags


def _combined_df():
    """Read every CSV in the data scope and concatenate (generates sample if empty)."""
    import pandas as pd

    ensure_portfolio()
    frames = []
    for f in list_csv_files():
        try:
            frames.append(pd.read_csv(f))
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _normalise_col(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower())).strip("_")


def _non_empty_ratio(series) -> float:
    if len(series) == 0:
        return 0.0
    values = series.fillna("").astype(str).str.strip()
    values = values[~values.str.lower().isin(("", "nan", "none", "null"))]
    return float(len(values)) / float(len(series))


def _field_score(field: str, col: str) -> int:
    candidates = _COLUMN_CANDIDATES.get(field, ())
    if col in candidates:
        return 120 - list(candidates).index(col)

    parts = set(col.split("_"))
    if field == "app_id":
        if "id" in parts and ({"app", "application"} & parts):
            return 100
        if col == "id":
            return 70
    elif field == "app_name":
        if "name" in parts and ({"app", "application", "system", "service"} & parts):
            return 100
        if col == "name":
            return 65
    elif field == "owner":
        if "owner" in parts or col.endswith("_owner") or "owner" in col:
            return 115
        if {"responsible", "accountable", "custodian"} & parts:
            return 85
    elif field == "lifecycle_state":
        if "lifecycle" in parts or {"phase", "state"} & parts:
            return 95
        if col == "status":
            return 55
    elif field == "business_criticality":
        if "criticality" in parts or ("business" in parts and "impact" in parts):
            return 105
        if "impact" in parts:
            return 75
    elif field == "technical_maturity":
        if "maturity" in parts and ({"technical", "technology", "tech"} & parts):
            return 105
        if "maturity" in parts:
            return 80
    elif field == "last_reviewed_date":
        if "review" in parts and ({"date", "reviewed", "last"} & parts):
            return 105
        if {"assessment", "assessed"} & parts and "date" in parts:
            return 85
    elif field == "compliance_status":
        if "compliance" in parts:
            return 105
        if "policy" in parts and "status" in parts:
            return 85
    elif field == "hosting":
        if {"hosting", "deployment", "platform"} & parts:
            return 95
    elif field == "annual_cost":
        if "cost" in parts and ({"annual", "yearly", "run", "total"} & parts):
            return 105
        if "cost" in parts:
            return 80
    return 0


def _select_source_column(df, field: str) -> str | None:
    best_col = None
    best_score = 0.0
    for col in df.columns:
        score = _field_score(field, col)
        if score <= 0:
            continue
        ratio = _non_empty_ratio(df[col])
        score = score + min(20.0, ratio * 20.0)
        if ratio == 0:
            score -= 50.0
        if score > best_score:
            best_score = score
            best_col = col
    return best_col if best_score >= 60 else None


def _normalise_df(df):
    """Normalize user-uploaded CSVs into the detector's expected portfolio shape."""
    df = df.copy()
    original_by_norm = {}
    normalised_cols = []
    for c in df.columns:
        norm = _normalise_col(c)
        original_by_norm.setdefault(norm, str(c))
        normalised_cols.append(norm)
    df.columns = normalised_cols

    mapping = {}
    synthetic_columns = set()
    for field in STANDARD_FIELDS:
        src = _select_source_column(df, field)
        if src is not None:
            if src != field:
                df[field] = df[src]
            mapping[field] = original_by_norm.get(src, src)
        else:
            mapping[field] = None
            synthetic_columns.add(field)

    if "app_id" not in df.columns:
        df["app_id"] = [f"UPLOAD-{i + 1:04d}" for i in range(len(df))]
        synthetic_columns.add("app_id")
    else:
        ids = df["app_id"].fillna("").astype(str).str.strip()
        missing = ids.str.lower().isin(("", "nan", "none"))
        ids.loc[missing] = [f"UPLOAD-{i + 1:04d}" for i in range(missing.sum())]
        df["app_id"] = ids

    defaults = {
        "app_name": "",
        "owner": "",
        "lifecycle_state": "run",
        "business_criticality": "medium",
        "technical_maturity": 3,
        "last_reviewed_date": date.today().isoformat(),
        "compliance_status": "unknown",
        "hosting": "hybrid",
        "annual_cost": 0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default
        else:
            df[col] = df[col].fillna(default)

    for col in ("lifecycle_state", "business_criticality", "compliance_status", "hosting"):
        df[col] = (
            df[col].astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
            .str.replace("-", "_", regex=False)
        )
    df["owner"] = df["owner"].fillna("").astype(str)
    df["last_reviewed_date"] = df["last_reviewed_date"].fillna(date.today().isoformat()).astype(str)
    df["technical_maturity"] = df["technical_maturity"].fillna(3)
    df["annual_cost"] = df["annual_cost"].fillna(0)
    df.attrs["field_mapping"] = mapping
    df.attrs["synthetic_columns"] = synthetic_columns
    return df


def build_governance_tasks(payload: dict, normalised_df) -> list[dict]:
    # Pure and deterministic: same payload and dataframe always yield the same tasks.
    rows_by_id: dict[str, dict] = {}
    for _, row in normalised_df.iterrows():
        record = row.to_dict()
        app_id = str(record.get("app_id") or "").strip()
        if app_id and app_id not in rows_by_id:
            rows_by_id[app_id] = record

    tasks = []
    for flag in payload.get("flagged_records") or []:
        app_id = str(flag.get("app_id") or "").strip()
        source = str(flag.get("source") or "rule")
        reason = str(flag.get("reason") or "unknown_issue")
        row = rows_by_id.get(app_id, {})

        owner = str(row.get("owner") or "").strip()
        if owner.lower() in ("", "nan", "none", "null"):
            owner = config.GOVERNANCE_TASK_FALLBACK_OWNER

        title, action_template, evidence_fields = _TASK_COPY.get(
            reason,
            (reason.replace("_", " ").strip().title(), "Review the flagged issue for {app_id}.", ()),
        )
        if source == "isolation_forest":
            evidence = dict(flag.get("feature_contributions") or {})
        else:
            evidence = {field: _plain_value(row.get(field)) for field in evidence_fields}

        tasks.append({
            "app_id": app_id,
            "title": title,
            "action": action_template.format(app_id=app_id),
            "suggested_owner": owner,
            "source": source,
            "reason": reason,
            "anomaly_score": flag.get("score"),
            "evidence": evidence,
        })
    return tasks


def _plain_value(value):
    """Convert NumPy scalar values to ordinary Python values for stable evidence."""
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    return value


def detect(csv_path=None) -> dict:
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import IsolationForest

    if csv_path is not None:
        df = pd.read_csv(csv_path)
    else:
        df = _combined_df()
    df = _normalise_df(df)
    df = df.fillna({"owner": "", "compliance_status": "unknown"})
    if df.empty:
        return {"flagged_records": [], "summary": {"total": 0, "rule_flags": 0, "ml_flags": 0}}
    today = date.today()
    synthetic_columns = set(df.attrs.get("synthetic_columns", set()))
    field_mapping = dict(df.attrs.get("field_mapping", {}))

    flagged = _rule_checks(df, today, synthetic_columns)
    rule_flags = len(flagged)

    # Categoricals are ordinal-encoded; cost is log-scaled so it does not dominate splits.
    enc = pd.DataFrame({
        "lifecycle": df["lifecycle_state"].map({v: i for i, v in enumerate(LIFECYCLE)}).fillna(0),
        "criticality": df["business_criticality"].map({v: i for i, v in enumerate(CRITICALITY)}).fillna(0),
        "compliance": df["compliance_status"].map({v: i for i, v in enumerate(COMPLIANCE)}).fillna(2),
        "hosting": df["hosting"].map({v: i for i, v in enumerate(HOSTING)}).fillna(0),
        "maturity": pd.to_numeric(df["technical_maturity"], errors="coerce").fillna(3),
        "log_cost": np.log1p(pd.to_numeric(df["annual_cost"], errors="coerce").fillna(0)),
    })
    # contamination 0.05 sets the 5% outlier operating point; seed fixed for reproducibility.
    model = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
    preds = model.fit_predict(enc.values)
    scores = model.decision_function(enc.values)
    for i, (pred, score) in enumerate(zip(preds, scores)):
        if pred == -1:
            row = df.iloc[i]
            maturity = pd.to_numeric(row["technical_maturity"], errors="coerce")
            cost = pd.to_numeric(row["annual_cost"], errors="coerce")
            flagged.append({
                "app_id": row["app_id"],
                "reason": "statistical_outlier",
                "source": "isolation_forest",
                "score": round(float(score), 4),
                "feature_contributions": {
                    "lifecycle_state": row["lifecycle_state"],
                    "business_criticality": row["business_criticality"],
                    "technical_maturity": int(maturity) if not pd.isna(maturity) else 3,
                    "annual_cost": int(cost) if not pd.isna(cost) else 0,
                },
            })
    ml_flags = len(flagged) - rule_flags

    payload = {
        "flagged_records": flagged,
        "summary": {
            "total": int(len(df)),
            "rule_flags": rule_flags,
            "ml_flags": ml_flags,
            "field_mapping": field_mapping,
            "skipped_missing_fields": sorted(synthetic_columns),
        },
    }
    store.create_governance_tasks(build_governance_tasks(payload, df))
    return payload


# --- cached active payload (consumed by the Domain Agent) ----------------------
def get_payload(refresh: bool = False) -> dict:
    global _payload_cache
    if _payload_cache is None or refresh:
        _payload_cache = detect()
    return _payload_cache


def current_payload() -> dict | None:
    """Return the active payload WITHOUT triggering detection (None if not yet run)."""
    return _payload_cache


def clear_cache() -> None:
    global _payload_cache
    _payload_cache = None
