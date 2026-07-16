from __future__ import annotations

import hashlib
import sqlite3
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import numpy as np
import yaml
from openpyxl.styles import Alignment, Font, PatternFill

CANONICAL_COLUMNS = {
    "transaction_id": ["transaction id", "payment public id", "payment id", "order id", "merchant order id"],
    "merchant": ["merchant", "merchant name"],
    "mid": ["mid", "merchant id"],
    "transaction_date": ["transaction date", "date", "trx date", "created at", "creation date"],
    "type": ["type", "transaction type"],
    "status": ["status", "transaction status"],
    "amount": ["amount", "trx amount", "transaction amount", "initial amount"],
    "merchant_amount": ["merchant amount", "amount to merchant", "to merchant", "settlement amount", "net amount"],
    "currency": ["currency"],
    "brand": ["brand", "card brand"],
    "card_number": ["number", "card number", "pan", "masked pan"],
    "payer_name": ["payer name", "customer name"],
    "payer_country": ["payer country", "customer country"],
    "payer_email": ["payer email", "email", "customer email"],
    "payer_phone": ["payer phone", "phone", "customer phone"],
    "geoip_country": ["payer geoip country", "geoip country", "ip country"],
    "gateway_id": ["gateway id"],
    "card_type": ["type of card", "card type"],
    "card_category": ["category of card", "card category"],
    "issuer": ["issuer", "bank", "issuing bank"],
    "issuer_country": ["issuer country", "bank country"],
    "decline_reason": ["decline reason", "decline reason translated", "reason"],
    "decline_type": ["decline type", "decline category"],
}

SEVERITY_POINTS = {"Low": 10, "Medium": 25, "High": 45, "Critical": 70}
ALERT_COLUMNS = [
    "row_number", "transaction_id", "merchant", "mid", "brand", "transaction_date",
    "amount", "merchant_amount", "currency", "status", "card_token", "card_display",
    "payer_email", "payer_phone", "rule", "rule_name", "rule_family", "classification",
    "severity", "points", "reason", "advice", "rule_scope", "aggregation_key",
    "limit_value", "observed_value", "baseline_value", "evidence", "alert_status",
]


def load_rules(path: str | Path = "rules.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalise_header(name: Any) -> str:
    return str(name).strip().lower().replace("_", " ")


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_phone(value: Any) -> str:
    return "".join(char for char in str(value or "") if char.isdigit() or char == "+")


def _brand_key(value: Any) -> str:
    brand = _norm_key(value)
    if brand in {"mc", "master card", "mastercard", "maestro"}:
        return "mastercard"
    if brand in {"visa", "v"}:
        return "visa"
    return brand


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int | None = None) -> int | None:
    parsed = _to_float(value, None)
    return int(parsed) if parsed is not None else default


def infer_column_map(df: pd.DataFrame) -> Dict[str, str]:
    headers = {_normalise_header(c): c for c in df.columns}
    out = {}
    for canonical, synonyms in CANONICAL_COLUMNS.items():
        for s in synonyms:
            if s in headers:
                out[canonical] = headers[s]
                break
    return out


def read_upload(uploaded_file) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def validate_upload(
    df: pd.DataFrame,
    column_map: Dict[str, str] | None = None,
    max_rows: int = 100_000,
) -> pd.DataFrame:
    """Return blocking errors and quality warnings before normalization/evaluation."""
    issues: list[dict[str, str]] = []
    column_map = column_map or infer_column_map(df)

    def add(severity: str, issue: str, field: str, detail: str) -> None:
        issues.append({"severity": severity, "issue": issue, "field": field, "detail": detail})

    if df.empty:
        add("Error", "Empty file", "file", "The upload contains no transaction rows.")
    if len(df) > max_rows:
        add("Error", "Row limit exceeded", "file", f"{len(df):,} rows exceed the {max_rows:,}-row public demo limit.")

    required = ["transaction_date", "merchant", "mid", "status", "amount"]
    for field in required:
        source = column_map.get(field)
        if not source or source not in df.columns:
            add("Error", "Required mapping missing", field, f"Map a source column to `{field}` before normalization.")

    for field in ["merchant", "mid", "status"]:
        source = column_map.get(field)
        if not source or source not in df.columns or df.empty:
            continue
        missing = df[source].isna() | df[source].astype(str).str.strip().eq("")
        rate = float(missing.mean())
        if rate:
            severity = "Error" if rate >= 0.50 else "Warning"
            add(severity, "Missing critical values", field, f"{rate:.1%} of rows have no usable `{field}` value.")

    date_source = column_map.get("transaction_date")
    if date_source in df.columns and not df.empty:
        invalid = pd.to_datetime(df[date_source], errors="coerce").isna()
        rate = float(invalid.mean())
        if rate:
            severity = "Error" if rate >= 0.50 else "Warning"
            add(severity, "Unparseable dates", "transaction_date", f"{rate:.1%} of dates cannot be parsed.")

    amount_source = column_map.get("amount")
    if amount_source in df.columns and not df.empty:
        invalid = pd.to_numeric(df[amount_source], errors="coerce").isna()
        rate = float(invalid.mean())
        if rate:
            severity = "Error" if rate >= 0.50 else "Warning"
            add(severity, "Non-numeric amounts", "amount", f"{rate:.1%} of transaction amounts are not numeric.")

    transaction_source = column_map.get("transaction_id")
    if transaction_source in df.columns and not df.empty:
        populated = df[transaction_source].dropna().astype(str).str.strip()
        duplicate_count = int(populated[populated.ne("")].duplicated(keep=False).sum())
        if duplicate_count:
            add("Warning", "Duplicate transaction IDs", "transaction_id", f"{duplicate_count:,} rows share a transaction ID; row identity will keep them separate.")

    return pd.DataFrame(issues, columns=["severity", "issue", "field", "detail"])


def normalize_transactions(df: pd.DataFrame, column_map: Dict[str, str] | None = None) -> pd.DataFrame:
    column_map = column_map or infer_column_map(df)
    norm = pd.DataFrame()
    for canonical in CANONICAL_COLUMNS:
        source = column_map.get(canonical)
        norm[canonical] = df[source] if source in df.columns else None

    norm["transaction_date"] = pd.to_datetime(norm["transaction_date"], errors="coerce")
    norm["amount"] = pd.to_numeric(norm["amount"], errors="coerce").fillna(0)
    norm["merchant_amount"] = pd.to_numeric(norm["merchant_amount"], errors="coerce").fillna(norm["amount"])
    for c in [
        "merchant", "mid", "status", "type", "currency", "brand", "card_number", "payer_name",
        "payer_email", "payer_phone", "payer_country", "geoip_country", "issuer",
        "issuer_country", "decline_reason", "decline_type", "gateway_id", "card_type", "card_category",
    ]:
        norm[c] = norm[c].fillna("").astype(str).str.strip()
    norm["transaction_day"] = norm["transaction_date"].dt.date
    norm["transaction_week"] = norm["transaction_date"].dt.to_period("W-MON").astype(str).replace("NaT", "")
    norm["transaction_month"] = norm["transaction_date"].dt.to_period("M").astype(str).replace("NaT", "")
    norm["transaction_hour"] = norm["transaction_date"].dt.hour
    norm["status_l"] = norm["status"].str.lower()
    norm["brand_key"] = norm["brand"].apply(_brand_key)
    norm["card_hash"] = norm["card_number"].apply(lambda x: hashlib.sha256(str(x).encode()).hexdigest()[:16] if x else "")
    norm["card_display"] = norm["card_number"].apply(
        lambda x: f"****{str(x)[-4:]}" if str(x).strip() else ""
    )
    norm["email_key"] = norm["payer_email"].str.strip().str.lower()
    norm["phone_key"] = norm["payer_phone"].str.replace(r"[^0-9+]", "", regex=True)
    if norm["transaction_id"].isna().all() or (norm["transaction_id"].astype(str).str.strip() == "").all():
        norm["transaction_id"] = [f"row-{i+1}" for i in range(len(norm))]
    norm["row_number"] = range(1, len(norm) + 1)
    return norm


def spreadsheet_safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Prevent formula execution while preserving user-controlled text in exports."""
    out = df.copy()

    def safe(value: Any) -> Any:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    for column in out.select_dtypes(include=["object", "string"]).columns:
        out[column] = out[column].map(safe)
    return out


def plan_for_row(row: pd.Series, rules: dict) -> str:
    mid = str(row.get("mid", ""))
    merchant = str(row.get("merchant", ""))
    if mid in (rules.get("mid_plan_map") or {}):
        return rules["mid_plan_map"][mid]
    if merchant in (rules.get("merchant_plan_map") or {}):
        return rules["merchant_plan_map"][merchant]
    desc = f"{merchant} {row.get('type','')} {row.get('card_category','')}".lower()
    if "forex" in desc:
        return "FOREX"
    if "gaming" in desc or "bet" in desc or "casino" in desc:
        return "GAMING"
    return "STANDARD"


def effective_limits(row: pd.Series, rules: dict) -> dict:
    g = dict(rules.get("global", {}))
    plan = plan_for_row(row, rules)
    g.update(rules.get("plans", {}).get(plan, {}))
    merchant = str(row.get("merchant", ""))
    mid = str(row.get("mid", ""))
    applied_scope = f"plan:{plan}"
    g.update(_detailed_rule_limits(row, rules, "merchant_rules", merchant))
    if merchant in (rules.get("merchant_rules") or {}):
        applied_scope = f"merchant:{merchant}"
    g.update((rules.get("merchant_overrides") or {}).get(merchant, {}))
    if merchant in (rules.get("merchant_overrides") or {}):
        applied_scope = f"merchant:{merchant}"
    g.update(_detailed_rule_limits(row, rules, "mid_rules", mid))
    if mid in (rules.get("mid_rules") or {}):
        applied_scope = f"mid:{mid}"
    g.update((rules.get("mid_overrides") or {}).get(mid, {}))
    if mid in (rules.get("mid_overrides") or {}):
        applied_scope = f"mid:{mid}"
    for override in rules.get("temporary_overrides") or []:
        if _temporary_override_applies(override, row):
            g.update(override.get("values") or {})
            applied_scope = f"temporary:{override.get('id', 'override')}"
    g["plan"] = plan
    g["rule_scope"] = applied_scope
    return g


def _temporary_override_applies(override: dict, row: pd.Series) -> bool:
    """Return whether a governed, expiring override applies to this transaction."""
    if not isinstance(override, dict) or not override.get("enabled", True):
        return False
    merchant, mid = str(row.get("merchant", "")), str(row.get("mid", ""))
    if override.get("merchant") and str(override["merchant"]) != merchant:
        return False
    if override.get("mid") and str(override["mid"]) != mid:
        return False
    when = pd.to_datetime(row.get("transaction_date"), errors="coerce", utc=True)
    when = when if pd.notna(when) else pd.Timestamp.now(tz="UTC")
    starts = pd.to_datetime(override.get("starts_at"), errors="coerce", utc=True)
    expires = pd.to_datetime(override.get("expires_at"), errors="coerce", utc=True)
    if pd.notna(starts) and when < starts:
        return False
    if pd.notna(expires) and when > expires:
        return False
    return True


def _detailed_rule_limits(row: pd.Series, rules: dict, section: str, entity: str) -> dict:
    config = (rules.get(section) or {}).get(str(entity), {})
    if not isinstance(config, dict):
        return {}

    out: dict[str, Any] = {}
    actual = config.get("actual_value") or {}
    merchant_value = config.get("merchant_value") or {}
    if "min" in actual:
        out["min_amount"] = actual["min"]
    if "max" in actual:
        out["max_amount"] = actual["max"]
    if "min" in merchant_value:
        out["merchant_min_amount"] = merchant_value["min"]
    if "max" in merchant_value:
        out["merchant_max_amount"] = merchant_value["max"]

    brand_key = _brand_key(row.get("brand_key") or row.get("brand"))
    brand_rules = config.get("brand_rules") or {}
    brand_config = brand_rules.get(brand_key) or brand_rules.get("all") or {}
    if "successful_limit" in brand_config:
        out["card_approved_count_limit"] = brand_config["successful_limit"]
    if "successful_window_hours" in brand_config:
        out["card_approved_window_hours"] = brand_config["successful_window_hours"]
    if "failed_limit" in brand_config:
        out["card_declined_count_limit"] = brand_config["failed_limit"]
    if "failed_window_hours" in brand_config:
        out["card_declined_window_hours"] = brand_config["failed_window_hours"]
    if "daily_volume_limit" in brand_config:
        out["daily_merchant_volume"] = brand_config["daily_volume_limit"]
    return out


def rule_definition(rules: dict, code: str) -> dict:
    for definition in rules.get("rule_catalog") or []:
        if definition.get("code") == code:
            return definition
    return {}


def executable_rule(rules: dict, code: str) -> bool:
    definition = rule_definition(rules, code)
    return bool(
        definition
        and definition.get("enabled", False)
        and definition.get("classification") == "Monitoring Rule"
        and code not in set(rules.get("_disabled_rules") or [])
    )


def _rolling_counts(tx: pd.DataFrame, status_col: str, window_col: str, output_col: str) -> pd.Series:
    counts = np.zeros(len(tx), dtype="int64")
    eligible = (tx["card_hash"] != "") & tx["transaction_date"].notna()
    base = tx.loc[eligible].copy()
    base["_tm_position"] = np.flatnonzero(eligible.to_numpy())
    if base.empty:
        return pd.Series(counts, index=tx.index)
    group_cols = ["mid", "brand_key", "card_hash"]
    base["_window_hours"] = pd.to_numeric(base[window_col], errors="coerce").fillna(24).clip(lower=0.001)
    varying = base.groupby(group_cols, dropna=False)["_window_hours"].transform("nunique") > 1
    stable = base.loc[~varying]
    for window_hours, group in stable.groupby("_window_hours", dropna=False):
        ordered = group.sort_values(group_cols + ["transaction_date"])
        rolled = (
            ordered.groupby(group_cols, dropna=False, sort=False)
            .rolling(f"{float(window_hours)}h", on="transaction_date", closed="both")[status_col]
            .sum()
            .to_numpy(dtype="int64")
        )
        counts[ordered["_tm_position"].to_numpy()] = rolled
    # Temporary overrides can change a window within one entity group; preserve exact per-row semantics there.
    for _, group in base.loc[varying].groupby(group_cols, dropna=False):
        ordered = group.sort_values("transaction_date")
        dates = ordered["transaction_date"].astype("int64").to_numpy()
        windows = pd.to_numeric(ordered[window_col], errors="coerce").fillna(24).clip(lower=0.001).to_numpy()
        starts = dates - (windows * 3_600_000_000_000).astype("int64")
        left = np.searchsorted(dates, starts, side="left")
        flags = ordered[status_col].fillna(False).astype("int64").to_numpy()
        cumulative = np.concatenate(([0], np.cumsum(flags)))
        values = cumulative[np.arange(len(ordered)) + 1] - cumulative[left]
        counts[ordered["_tm_position"].to_numpy()] = values
    return pd.Series(counts, index=tx.index)


def _watchlist_sets(rules: dict) -> dict:
    watchlists = rules.get("watchlists") or {}
    return {
        "emails": {_norm_key(x) for x in watchlists.get("emails", []) if str(x).strip()},
        "phones": {_norm_phone(x) for x in watchlists.get("phones", []) if str(x).strip()},
        "cards": {str(x).strip() for x in watchlists.get("cards", []) if str(x).strip()},
        "bins": {str(x).strip() for x in watchlists.get("bins", []) if str(x).strip()},
    }


def _rule_severity(rules: dict, code: str, default: str) -> str:
    for rule in rules.get("rule_catalog", []):
        if rule.get("code") == code:
            return str(rule.get("severity") or default)
    return default



def evaluate(df: pd.DataFrame, rules: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate transactions with vectorized/grouped rules suitable for 100k+ rows."""
    tx = df.copy()
    tx["plan"] = tx.apply(lambda r: plan_for_row(r, rules), axis=1)
    tx["date_only"] = tx["transaction_date"].dt.date
    success = set(str(x).lower() for x in rules["global"].get("success_statuses", []))
    declines = set(str(x).lower() for x in rules["global"].get("decline_statuses", []))
    tx["is_success"] = tx["status_l"].isin(success)
    tx["is_decline"] = tx["status_l"].isin(declines)

    limits = tx.apply(lambda r: pd.Series(effective_limits(r, rules)), axis=1)
    for col in [
        "min_amount", "max_amount", "merchant_min_amount", "merchant_max_amount",
        "daily_merchant_volume", "card_approved_count_limit", "card_declined_count_limit",
        "card_approved_window_hours", "card_declined_window_hours",
    ]:
        tx[col] = pd.to_numeric(limits.get(col), errors="coerce")
    tx["effective_plan"] = limits.get("plan", "STANDARD")
    tx["rule_scope"] = limits.get("rule_scope", "").fillna("") if "rule_scope" in limits else ""

    alerts: List[Dict[str, Any]] = []

    def append_alerts(
        mask, rule: str, severity: str, reason_builder, advice: str,
        limit_builder=None, observed_builder=None, baseline_builder=None,
        aggregation_builder=None, evidence_builder=None,
    ):
        if not executable_rule(rules, rule):
            return
        definition = rule_definition(rules, rule)
        rows = tx.loc[mask]
        for _, r in rows.iterrows():
            reason = reason_builder(r) if callable(reason_builder) else reason_builder
            limit_value = limit_builder(r) if callable(limit_builder) else limit_builder
            observed_value = observed_builder(r) if callable(observed_builder) else observed_builder
            alerts.append({
                "row_number": int(r["row_number"]),
                "transaction_id": r["transaction_id"],
                "merchant": r["merchant"],
                "mid": r["mid"],
                "brand": r["brand"],
                "transaction_date": r["transaction_date"],
                "amount": r["amount"],
                "merchant_amount": r["merchant_amount"],
                "currency": r["currency"],
                "status": r["status"],
                "card_token": r.get("card_hash", ""),
                "card_display": r.get("card_display", ""),
                "payer_email": r["payer_email"],
                "payer_phone": r["payer_phone"],
                "rule": rule,
                "rule_name": definition.get("name", rule),
                "rule_family": definition.get("family", definition.get("group", "Uncategorised")),
                "classification": definition.get("classification", "Monitoring Rule"),
                "severity": severity,
                "points": int(definition.get("risk_weight", SEVERITY_POINTS.get(severity, 10))),
                "reason": reason,
                "advice": definition.get("recommended_analyst_action") or advice,
                "rule_scope": r.get("rule_scope", "") or r.get("effective_plan", "STANDARD"),
                "aggregation_key": aggregation_builder(r) if callable(aggregation_builder) else (aggregation_builder or r.get("mid", "")),
                "limit_value": limit_value,
                "observed_value": observed_value,
                "baseline_value": baseline_builder(r) if callable(baseline_builder) else baseline_builder,
                "evidence": evidence_builder(r) if callable(evidence_builder) else (evidence_builder or reason),
                "alert_status": "New",
            })

    # Preventive limits are retained as context but never generate TM alerts.
    control_masks = {
        "LOW_AMOUNT_BELOW_MINIMUM": tx["amount"] < tx["min_amount"].fillna(rules["global"].get("min_transaction_amount", 0)),
        "HIGH_AMOUNT_ABOVE_PLAN_LIMIT": tx["amount"] > tx["max_amount"].fillna(float("inf")),
        "MERCHANT_VALUE_BELOW_MINIMUM": tx["merchant_amount"] < tx["merchant_min_amount"].fillna(float("-inf")),
        "MERCHANT_VALUE_ABOVE_LIMIT": tx["merchant_amount"] > tx["merchant_max_amount"].fillna(float("inf")),
    }
    tx["preventive_control_breaches"] = ""
    for control_code, control_mask in control_masks.items():
        tx.loc[control_mask, "preventive_control_breaches"] = tx.loc[control_mask, "preventive_control_breaches"].apply(
            lambda current, code=control_code: "; ".join(x for x in [current, code] if x)
        )
    append_alerts((tx["payer_country"] != "") & (tx["geoip_country"] != "") & (tx["payer_country"].str.upper() != tx["geoip_country"].str.upper()),
                  "PAYER_COUNTRY_GEOIP_MISMATCH", _rule_severity(rules, "PAYER_COUNTRY_GEOIP_MISMATCH", "Medium"),
                  lambda r: f"Payer country {r['payer_country']} differs from GeoIP {r['geoip_country']}",
                  "Review geo mismatch alongside merchant/MID risk profile.",
                  None, lambda r: f"{r['payer_country']} vs {r['geoip_country']}")

    high_risk_countries = set(str(x).upper().strip() for x in rules.get("global", {}).get("high_risk_countries", []) if str(x).strip())
    if high_risk_countries:
        payer_hr = tx["payer_country"].str.upper().isin(high_risk_countries)
        geoip_hr = tx["geoip_country"].str.upper().isin(high_risk_countries)
        append_alerts(payer_hr | geoip_hr,
                      "HIGH_RISK_COUNTRY", _rule_severity(rules, "HIGH_RISK_COUNTRY", "High"),
                      lambda r: f"High-risk country match. Payer={r['payer_country']} GeoIP={r['geoip_country']}",
                      "Prioritize for compliance/risk review.",
                      ", ".join(sorted(high_risk_countries)), lambda r: f"{r['payer_country']}/{r['geoip_country']}")

    daily = tx[tx["is_success"]].groupby(["merchant", "mid", "brand_key", "date_only"], dropna=False)["amount"].sum().rename("daily_volume").reset_index()
    tx = tx.merge(daily, on=["merchant", "mid", "brand_key", "date_only"], how="left")
    daily_representative = ~tx.duplicated(["merchant", "mid", "brand_key", "date_only"], keep="last")
    append_alerts(daily_representative & (tx["daily_volume"].fillna(0) > tx["daily_merchant_volume"].fillna(float("inf"))),
                  "MERCHANT_DAILY_VOLUME", _rule_severity(rules, "MERCHANT_DAILY_VOLUME", "Critical"),
                  lambda r: f"MID/brand daily approved volume {r['daily_volume']:.2f} above {r['daily_merchant_volume']} limit",
                  "Escalate daily volume breach for payout/risk decision.",
                  lambda r: r["daily_merchant_volume"], lambda r: r["daily_volume"],
                  aggregation_builder=lambda r: f"{r['merchant']}|{r['mid']}|{r['brand_key']}")

    tx["card_approved_window_hours"] = tx["card_approved_window_hours"].fillna(rules["global"].get("monitoring_window_hours", 24))
    tx["card_declined_window_hours"] = tx["card_declined_window_hours"].fillna(rules["global"].get("monitoring_window_hours", 24))
    tx["card_success_count_window"] = _rolling_counts(tx, "is_success", "card_approved_window_hours", "card_success_count_window")
    tx["card_decline_count_window"] = _rolling_counts(tx, "is_decline", "card_declined_window_hours", "card_decline_count_window")
    append_alerts((tx["card_hash"] != "") & (tx["card_success_count_window"] > tx["card_approved_count_limit"].fillna(7)),
                  "CARD_APPROVED_VELOCITY", _rule_severity(rules, "CARD_APPROVED_VELOCITY", "High"),
                  lambda r: f"Same card has {int(r['card_success_count_window'])} successful transactions in {int(r['card_approved_window_hours'])} hours; limit is {int(r['card_approved_count_limit'])}",
                  "Highlight as velocity breach and review related transactions.",
                  lambda r: f"{int(r['card_approved_count_limit'])}/{int(r['card_approved_window_hours'])}h",
                  lambda r: int(r["card_success_count_window"]))
    append_alerts((tx["card_hash"] != "") & (tx["card_decline_count_window"] > tx["card_declined_count_limit"].fillna(3)),
                  "CARD_DECLINE_VELOCITY", _rule_severity(rules, "CARD_DECLINE_VELOCITY", "High"),
                  lambda r: f"Same card has {int(r['card_decline_count_window'])} failed transactions in {int(r['card_declined_window_hours'])} hours; limit is {int(r['card_declined_count_limit'])}",
                  "Review failed attempt burst and related successful transactions.",
                  lambda r: f"{int(r['card_declined_count_limit'])}/{int(r['card_declined_window_hours'])}h",
                  lambda r: int(r["card_decline_count_window"]))

    # Normalized identity values used with multiple cards per merchant.
    for field, rule_name, limit_key in [("email_key", "EMAIL_USED_WITH_MULTIPLE_CARDS", "email_multiple_card_limit"), ("phone_key", "PHONE_USED_WITH_MULTIPLE_CARDS", "phone_multiple_card_limit")]:
        base = tx[(tx[field] != "") & (tx["card_hash"] != "")]
        if not base.empty:
            counts = base.groupby(["merchant", field], dropna=False)["card_hash"].nunique().rename(f"{field}_card_count").reset_index()
            tx = tx.merge(counts, on=["merchant", field], how="left")
            col = f"{field}_card_count"
            append_alerts(tx[col].fillna(0) > int(rules["global"].get(limit_key, 2)),
                          rule_name, _rule_severity(rules, rule_name, "High"),
                          lambda r, f=field, c=col: f"{f} used with {int(r[c])} different cards within upload",
                          "Review identity linkage across cards.",
                          rules["global"].get(limit_key, 2), lambda r, c=col: int(r[c]),
                          aggregation_builder=lambda r, f=field: r[f])

    repeated_window = _to_float(rules.get("global", {}).get("repeated_amount_window_minutes"), 10) or 10
    repeated_counts = np.zeros(len(tx), dtype="int64")
    eligible = (tx["card_hash"] != "") & (tx["amount"] > 0) & tx["transaction_date"].notna()
    base = tx.loc[eligible].copy()
    base["_tm_position"] = np.flatnonzero(eligible.to_numpy())
    if not base.empty:
        group_cols = ["merchant", "card_hash", "amount"]
        base["_one"] = 1
        ordered = base.sort_values(group_cols + ["transaction_date"])
        rolled = (
            ordered.groupby(group_cols, dropna=False, sort=False)
            .rolling(f"{float(repeated_window)}min", on="transaction_date", closed="both")["_one"]
            .sum()
            .to_numpy(dtype="int64")
        )
        repeated_counts[ordered["_tm_position"].to_numpy()] = rolled
    tx["repeated_amount_count_window"] = repeated_counts
    append_alerts(tx["repeated_amount_count_window"] > 1,
                  "REPEATED_CARD_AMOUNT", _rule_severity(rules, "REPEATED_CARD_AMOUNT", "Medium"),
                  lambda r: f"Same card and amount repeated {int(r['repeated_amount_count_window'])} times within {int(repeated_window)} minutes",
                  "Review for split/retry pattern before export.",
                  f">1/{int(repeated_window)}m", lambda r: int(r["repeated_amount_count_window"]))

    watchlists = _watchlist_sets(rules)
    append_alerts(tx["payer_email"].str.lower().isin(watchlists["emails"]),
                  "WATCHLIST_EMAIL", _rule_severity(rules, "WATCHLIST_EMAIL", "Critical"),
                  lambda r: f"Email {r['payer_email']} appears on watchlist",
                  "Prioritize for analyst review.",
                  "watchlist", lambda r: r["payer_email"])
    append_alerts(tx["phone_key"].isin(watchlists["phones"]),
                  "WATCHLIST_PHONE", _rule_severity(rules, "WATCHLIST_PHONE", "Critical"),
                  lambda r: f"Phone {r['payer_phone']} appears on watchlist",
                  "Prioritize for analyst review.",
                  "watchlist", lambda r: r["payer_phone"])
    append_alerts(tx["card_number"].isin(watchlists["cards"]),
                  "WATCHLIST_CARD", _rule_severity(rules, "WATCHLIST_CARD", "Critical"),
                  "Card appears on watchlist",
                  "Prioritize for analyst review.",
                  "watchlist", lambda r: r["card_display"])
    append_alerts(tx["card_number"].astype(str).str[:6].isin(watchlists["bins"]),
                  "WATCHLIST_BIN", _rule_severity(rules, "WATCHLIST_BIN", "High"),
                  "Card BIN appears on watchlist",
                  "Review BIN exposure and merchant context.",
                  "watchlist", lambda r: str(r["card_number"])[:6])

    # Cross-merchant card linkage: one representative hit per card for the run.
    card_base = tx[tx["card_hash"] != ""]
    if not card_base.empty:
        card_merchants = card_base.groupby("card_hash")["merchant"].nunique().rename("card_merchant_count")
        tx = tx.merge(card_merchants, on="card_hash", how="left")
        cross_limit = int(rules.get("global", {}).get("cross_merchant_card_limit", 3))
        representative = ~tx.duplicated("card_hash", keep="last")
        append_alerts(
            representative & (tx["card_merchant_count"].fillna(0) >= cross_limit),
            "CARD_USED_ACROSS_MERCHANTS", _rule_severity(rules, "CARD_USED_ACROSS_MERCHANTS", "High"),
            lambda r: f"Card token appeared across {int(r['card_merchant_count'])} merchants in the evaluated period",
            "Review linked merchants, transaction purpose, statuses and customer identities.",
            cross_limit, lambda r: int(r["card_merchant_count"]),
            aggregation_builder=lambda r: r["card_hash"],
        )

    # A successful transaction after a concentrated decline burst is more useful than a raw decline count alone.
    decline_then_approval_limit = int(rules.get("global", {}).get("decline_then_approval_limit", 2))
    append_alerts(
        tx["is_success"] & (tx["card_hash"] != "") & (tx["card_decline_count_window"] >= decline_then_approval_limit),
        "DECLINE_THEN_APPROVAL", _rule_severity(rules, "DECLINE_THEN_APPROVAL", "High"),
        lambda r: f"Approval followed {int(r['card_decline_count_window'])} declines within {int(r['card_declined_window_hours'])} hours",
        "Check for card testing, credential compromise, rule evasion and issuer response patterns.",
        decline_then_approval_limit, lambda r: int(r["card_decline_count_window"]),
        aggregation_builder=lambda r: r["card_hash"],
    )

    # Deterministic trailing baselines (not machine learning). They activate only with enough prior days.
    min_history_days = int(rules.get("baseline_settings", {}).get("minimum_history_days", 7))
    baseline_days = int(rules.get("baseline_settings", {}).get("lookback_days", 30))
    daily_metrics = tx.groupby(["merchant", "mid", "date_only"], dropna=False).agg(
        daily_count=("transaction_id", "count"),
        daily_volume=("amount", lambda s: float(s[tx.loc[s.index, "is_success"]].sum())),
        daily_approvals=("is_success", "sum"),
        daily_declines=("is_decline", "sum"),
        daily_refunds=("type", lambda s: int(s.astype(str).str.lower().str.contains("refund|reversal", regex=True).sum())),
    ).reset_index().sort_values(["merchant", "mid", "date_only"])
    if not daily_metrics.empty:
        grouped = daily_metrics.groupby(["merchant", "mid"], dropna=False)
        for metric in ["daily_count", "daily_volume", "daily_approvals", "daily_declines", "daily_refunds"]:
            daily_metrics[f"{metric}_baseline"] = grouped[metric].transform(
                lambda values: values.shift(1).rolling(baseline_days, min_periods=min_history_days).mean()
            )
        daily_metrics["approval_rate"] = daily_metrics["daily_approvals"] / daily_metrics["daily_count"].replace(0, pd.NA)
        daily_metrics["approval_rate_baseline"] = daily_metrics.groupby(["merchant", "mid"], dropna=False)["approval_rate"].transform(
            lambda values: values.shift(1).rolling(baseline_days, min_periods=min_history_days).mean()
        )
        daily_metrics["refund_rate"] = daily_metrics["daily_refunds"] / daily_metrics["daily_count"].replace(0, pd.NA)
        daily_metrics["refund_rate_baseline"] = daily_metrics.groupby(["merchant", "mid"], dropna=False)["refund_rate"].transform(
            lambda values: values.shift(1).rolling(baseline_days, min_periods=min_history_days).mean()
        )
        daily_metrics = daily_metrics.rename(columns={
            "daily_count": "baseline_current_count",
            "daily_volume": "baseline_current_volume",
        })
        keep = [
            "merchant", "mid", "date_only", "baseline_current_count", "baseline_current_volume",
            "daily_count_baseline", "daily_volume_baseline",
            "approval_rate", "approval_rate_baseline", "refund_rate", "refund_rate_baseline",
        ]
        tx = tx.merge(daily_metrics[keep], on=["merchant", "mid", "date_only"], how="left")
        day_representative = ~tx.duplicated(["merchant", "mid", "date_only"], keep="last")
        volume_multiplier = float(rules.get("global", {}).get("merchant_volume_baseline_multiplier", 3.5))
        append_alerts(
            day_representative & tx["daily_volume_baseline"].notna()
            & (tx["baseline_current_volume"] > tx["daily_volume_baseline"] * volume_multiplier),
            "MERCHANT_VOLUME_BASELINE_SPIKE", _rule_severity(rules, "MERCHANT_VOLUME_BASELINE_SPIKE", "High"),
            lambda r: f"Approved daily volume {r['baseline_current_volume']:.2f} is {r['baseline_current_volume']/r['daily_volume_baseline']:.1f}x its trailing baseline",
            "Review the source of the volume change and compare linked customers, cards, countries and MIDs.",
            volume_multiplier, lambda r: r["baseline_current_volume"], lambda r: r["daily_volume_baseline"],
            aggregation_builder=lambda r: f"{r['merchant']}|{r['mid']}",
        )
        rate_drop = float(rules.get("global", {}).get("approval_rate_drop_points", 0.30))
        min_daily = int(rules.get("global", {}).get("baseline_min_daily_transactions", 10))
        append_alerts(
            day_representative & tx["approval_rate_baseline"].notna() & (tx["baseline_current_count"] >= min_daily)
            & (tx["approval_rate"] <= tx["approval_rate_baseline"] - rate_drop),
            "MERCHANT_APPROVAL_RATE_DROP", _rule_severity(rules, "MERCHANT_APPROVAL_RATE_DROP", "Medium"),
            lambda r: f"Approval rate fell to {r['approval_rate']:.1%} from a {r['approval_rate_baseline']:.1%} trailing baseline",
            "Review decline reasons, traffic sources and whether the change is concentrated in cards, countries or channels.",
            rate_drop, lambda r: r["approval_rate"], lambda r: r["approval_rate_baseline"],
            aggregation_builder=lambda r: f"{r['merchant']}|{r['mid']}",
        )
        refund_multiplier = float(rules.get("global", {}).get("refund_rate_baseline_multiplier", 3.0))
        append_alerts(
            day_representative & tx["refund_rate_baseline"].notna() & (tx["baseline_current_count"] >= min_daily)
            & (tx["refund_rate"] > tx["refund_rate_baseline"].clip(lower=0.01) * refund_multiplier),
            "MERCHANT_REFUND_RATE_SPIKE", _rule_severity(rules, "MERCHANT_REFUND_RATE_SPIKE", "High"),
            lambda r: f"Refund/reversal rate rose to {r['refund_rate']:.1%} from a {r['refund_rate_baseline']:.1%} trailing baseline",
            "Review refund destinations, original transaction linkage and merchant fulfilment explanations.",
            refund_multiplier, lambda r: r["refund_rate"], lambda r: r["refund_rate_baseline"],
            aggregation_builder=lambda r: f"{r['merchant']}|{r['mid']}",
        )

    # Dormancy is evaluated from observed transaction history and emits one hit on resumption.
    dated = tx[tx["transaction_date"].notna()].sort_values("transaction_date")
    if not dated.empty:
        previous = dated.groupby("mid", dropna=False)["transaction_date"].shift(1)
        tx.loc[dated.index, "mid_inactivity_days"] = (dated["transaction_date"] - previous).dt.total_seconds() / 86400
        dormant_days = int(rules.get("global", {}).get("dormant_mid_days", 30))
        append_alerts(
            tx["mid_inactivity_days"].fillna(0) >= dormant_days,
            "DORMANT_MID_RESUMPTION", _rule_severity(rules, "DORMANT_MID_RESUMPTION", "High"),
            lambda r: f"MID resumed after {int(r['mid_inactivity_days'])} inactive days",
            "Confirm the MID operating status and review resumed volume, customers, countries and payment instruments.",
            dormant_days, lambda r: int(r["mid_inactivity_days"]),
            aggregation_builder=lambda r: r["mid"],
        )

    alert_df = pd.DataFrame(alerts, columns=ALERT_COLUMNS)
    if not alert_df.empty:
        agg = alert_df.groupby("row_number").agg(
            risk_score=("points", "sum"),
            triggered_rules=("rule", lambda ss: "; ".join(sorted(set(ss)))),
            alert_reasons=("reason", lambda ss: " | ".join(map(str, ss))),
        ).reset_index()
        tx = tx.merge(agg, on="row_number", how="left")
    else:
        tx["risk_score"] = 0
        tx["triggered_rules"] = ""
        tx["alert_reasons"] = ""
    tx["risk_score"] = tx["risk_score"].fillna(0).astype(int)
    tx["risk_level"] = pd.cut(tx["risk_score"], bins=[-1, 0, 24, 59, 99, 10**9], labels=["None", "Low", "Medium", "High", "Critical"])
    return tx, alert_df


def data_quality_report(tx: pd.DataFrame) -> pd.DataFrame:
    """Describe rule-critical field quality without creating suspicious-activity alerts."""
    dependencies = {
        "transaction_id": "All evidence and exports",
        "transaction_date": "Velocity, baselines and dormancy",
        "merchant": "Merchant monitoring and inheritance",
        "mid": "MID monitoring and inheritance",
        "status": "Approval, decline and refund behaviour",
        "amount": "Volume and amount behaviour",
        "card_hash": "Card velocity and linkage",
        "payer_email": "Customer identity linkage",
        "payer_phone": "Customer identity linkage",
        "payer_country": "Geographic monitoring",
        "geoip_country": "Geographic mismatch monitoring",
    }
    rows = []
    total = len(tx)
    for field, used_by in dependencies.items():
        if field not in tx:
            missing = total
        elif field == "transaction_date":
            missing = int(tx[field].isna().sum())
        else:
            missing = int((tx[field].isna() | (tx[field].astype(str).str.strip() == "")).sum())
        rate = missing / total if total else 0
        rows.append({
            "field": field,
            "missing_rows": missing,
            "missing_rate": rate,
            "quality_status": "Critical" if rate >= 0.50 else "Warning" if rate >= 0.10 else "Usable",
            "rules_affected": used_by,
        })
    return pd.DataFrame(rows)


def _case_story(rule_codes: set[str], families: set[str]) -> tuple[str, str]:
    if "DECLINE_THEN_APPROVAL" in rule_codes or {"CARD_DECLINE_VELOCITY", "CARD_APPROVED_VELOCITY"}.issubset(rule_codes):
        return "Possible card testing or credential compromise", "Validate issuer responses, linked identities and the approval following failed attempts."
    if "CARD_USED_ACROSS_MERCHANTS" in rule_codes:
        return "Unusual payment instrument activity across merchants", "Review whether the merchants are related and whether the customer and purchase context is credible."
    if "MERCHANT_VOLUME_BASELINE_SPIKE" in rule_codes:
        return "Material merchant or MID behaviour change", "Validate the business explanation and inspect new cards, countries, customers and traffic sources."
    if "MERCHANT_REFUND_RATE_SPIKE" in rule_codes:
        return "Possible refund or reversal abuse", "Trace refunds to original payments and review beneficiaries, timing and merchant fulfilment."
    if "DORMANT_MID_RESUMPTION" in rule_codes:
        return "Dormant MID resumed activity", "Confirm authorization to resume processing and review the first transactions as a linked set."
    if "Customer identity" in families and ("Geography" in families or "Velocity" in families):
        return "Possible account takeover or synthetic identity behaviour", "Review the linked identity, location, payment instruments and attempt sequence."
    if "Watchlist intelligence" in families:
        return "Watchlist-linked transaction activity", "Validate the match and follow the applicable escalation procedure."
    return "Related monitoring indicators require review", "Review the evidence, linked entities and transaction timeline before disposition."


def build_alert_cases(tx: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    """Combine related rule hits into investigation cases while retaining every raw hit."""
    columns = [
        "alert_id", "severity", "risk_score", "merchant", "mid", "primary_entity",
        "investigative_insight", "triggered_rules", "rule_families", "triggered_rule_count",
        "transaction_count", "total_amount", "approved_amount", "decline_count",
        "first_activity_time", "last_activity_time", "baseline_comparison", "top_risk_drivers",
        "related_cards", "related_emails", "related_phones", "recommended_action",
        "supporting_row_numbers", "supporting_transaction_ids", "status",
    ]
    if alerts is None or alerts.empty:
        return pd.DataFrame(columns=columns)
    work = alerts.copy()
    work["case_day"] = pd.to_datetime(work["transaction_date"], errors="coerce").dt.strftime("%Y-%m-%d").fillna("undated")
    work["aggregation_key"] = work["aggregation_key"].fillna("").astype(str)
    work.loc[work["aggregation_key"] == "", "aggregation_key"] = work.loc[work["aggregation_key"] == "", "mid"].astype(str)
    rank = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
    rows = []
    for keys, hits in work.groupby(["merchant", "mid", "aggregation_key", "case_day"], dropna=False, sort=False):
        merchant, mid, entity, case_day = keys
        rule_codes = set(hits["rule"].dropna().astype(str))
        families = set(hits["rule_family"].dropna().astype(str))
        insight, default_action = _case_story(rule_codes, families)
        severity = max(hits["severity"].astype(str), key=lambda value: rank.get(value, 0))
        unique_rule_points = hits.sort_values("points", ascending=False).drop_duplicates("rule")["points"].sum()
        source_rows = sorted(set(pd.to_numeric(hits["row_number"], errors="coerce").dropna().astype(int)))
        related_tx = tx[tx["row_number"].isin(source_rows)].copy()
        success = related_tx.get("is_success", pd.Series(False, index=related_tx.index)).fillna(False)
        decline = related_tx.get("is_decline", pd.Series(False, index=related_tx.index)).fillna(False)
        baselines = []
        for _, hit in hits[hits["baseline_value"].notna()].iterrows():
            baselines.append(f"{hit['rule_name']}: current {hit['observed_value']} vs baseline {hit['baseline_value']}")
        digest = hashlib.sha256(f"{merchant}|{mid}|{entity}|{case_day}".encode()).hexdigest()[:12].upper()
        rows.append({
            "alert_id": f"ALT-{digest}",
            "severity": severity,
            "risk_score": min(int(unique_rule_points), 100),
            "merchant": merchant,
            "mid": mid,
            "primary_entity": entity,
            "investigative_insight": insight,
            "triggered_rules": "; ".join(sorted(rule_codes)),
            "rule_families": "; ".join(sorted(families)),
            "triggered_rule_count": len(rule_codes),
            "transaction_count": int(related_tx["transaction_id"].nunique()) if not related_tx.empty else int(hits["transaction_id"].nunique()),
            "total_amount": float(related_tx["amount"].sum()) if not related_tx.empty else float(hits["amount"].sum()),
            "approved_amount": float(related_tx.loc[success, "amount"].sum()) if not related_tx.empty else 0.0,
            "decline_count": int(decline.sum()) if not related_tx.empty else int(hits["status"].astype(str).str.lower().isin({"fail", "failed", "declined", "rejected"}).sum()),
            "first_activity_time": pd.to_datetime(hits["transaction_date"], errors="coerce").min(),
            "last_activity_time": pd.to_datetime(hits["transaction_date"], errors="coerce").max(),
            "baseline_comparison": " | ".join(dict.fromkeys(baselines)),
            "top_risk_drivers": " | ".join(dict.fromkeys(hits.sort_values("points", ascending=False)["reason"].astype(str).head(4))),
            "related_cards": "; ".join(sorted(set(hits["card_display"].dropna().astype(str)) - {""})),
            "related_emails": "; ".join(sorted(set(hits["payer_email"].dropna().astype(str)) - {""})),
            "related_phones": "; ".join(sorted(set(hits["payer_phone"].dropna().astype(str)) - {""})),
            "recommended_action": next((str(x) for x in hits["advice"] if str(x).strip()), default_action),
            "supporting_row_numbers": "; ".join(map(str, source_rows)),
            "supporting_transaction_ids": "; ".join(sorted(set(hits["transaction_id"].dropna().astype(str)))),
            "status": "New",
        })
    cases = pd.DataFrame(rows, columns=columns)
    cases["severity_rank"] = cases["severity"].map(rank).fillna(0)
    return cases.sort_values(["severity_rank", "risk_score", "last_activity_time"], ascending=[False, False, False]).drop(columns="severity_rank")


def rule_performance(alerts: pd.DataFrame, cases: pd.DataFrame, tx_count: int, rules: dict) -> pd.DataFrame:
    catalog = pd.DataFrame(rules.get("rule_catalog") or [])
    if catalog.empty:
        return catalog
    if alerts is None or alerts.empty:
        stats = pd.DataFrame(columns=["code", "alerts_generated", "transactions_matched", "top_merchants", "top_mids"])
    else:
        stats_rows = []
        for code, hits in alerts.groupby("rule"):
            stats_rows.append({
                "code": code,
                "alerts_generated": len(hits),
                "transactions_matched": hits["row_number"].nunique(),
                "top_merchants": "; ".join(hits["merchant"].value_counts().head(3).index.astype(str)),
                "top_mids": "; ".join(hits["mid"].value_counts().head(3).index.astype(str)),
            })
        stats = pd.DataFrame(stats_rows)
    out = catalog.merge(stats, on="code", how="left")
    out["alerts_generated"] = pd.to_numeric(out.get("alerts_generated"), errors="coerce").fillna(0).astype(int)
    out["transactions_matched"] = pd.to_numeric(out.get("transactions_matched"), errors="coerce").fillna(0).astype(int)
    out["alert_rate"] = out["transactions_matched"] / max(tx_count, 1)
    out["volume_status"] = out["alert_rate"].apply(lambda rate: "Excessive" if rate >= 0.20 else "Review" if rate >= 0.05 else "Normal")
    return out


def simulate_rule_change(tx: pd.DataFrame, current_rules: dict, proposed_rules: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare proposed rules with current settings on the same historical upload."""
    current_tx, current_hits = evaluate(tx, deepcopy(current_rules))
    proposed_tx, proposed_hits = evaluate(tx, deepcopy(proposed_rules))
    current_cases = build_alert_cases(current_tx, current_hits)
    proposed_cases = build_alert_cases(proposed_tx, proposed_hits)

    def summary(label: str, evaluated: pd.DataFrame, hits: pd.DataFrame, cases: pd.DataFrame) -> dict:
        severity_counts = cases["severity"].value_counts() if not cases.empty else pd.Series(dtype=int)
        matched = int(evaluated["risk_score"].gt(0).sum())
        merchant_concentration = float(hits["merchant"].value_counts(normalize=True).iloc[0]) if not hits.empty else 0.0
        return {
            "setting": label,
            "transactions_evaluated": len(evaluated),
            "transactions_matched": matched,
            "alerts_generated": len(cases),
            "rule_hits": len(hits),
            "alert_rate": matched / max(len(evaluated), 1),
            "critical": int(severity_counts.get("Critical", 0)),
            "high": int(severity_counts.get("High", 0)),
            "medium": int(severity_counts.get("Medium", 0)),
            "low": int(severity_counts.get("Low", 0)),
            "estimated_false_positive_concentration": merchant_concentration,
            "volume_warning": "Excessive" if matched / max(len(evaluated), 1) >= 0.20 else "Review" if matched / max(len(evaluated), 1) >= 0.05 else "Normal",
        }
    comparison = pd.DataFrame([
        summary("Current", current_tx, current_hits, current_cases),
        summary("Proposed", proposed_tx, proposed_hits, proposed_cases),
    ])
    affected = proposed_hits.groupby(["merchant", "mid"], dropna=False).agg(
        rule_hits=("rule", "count"), transactions_matched=("row_number", "nunique")
    ).reset_index().sort_values("rule_hits", ascending=False) if not proposed_hits.empty else pd.DataFrame()
    return comparison, affected

def save_to_sqlite(tx: pd.DataFrame, alerts: pd.DataFrame, path: str | Path = "tm_history.db", cases: pd.DataFrame | None = None):
    conn = sqlite3.connect(path)
    tx.to_sql("transactions", conn, if_exists="append", index=False)
    alerts.to_sql("alerts", conn, if_exists="append", index=False)
    if cases is not None and not cases.empty:
        cases.to_sql("investigation_alerts", conn, if_exists="append", index=False)
    conn.close()


def _write_sheet(writer: pd.ExcelWriter, df: pd.DataFrame, sheet_name: str, index: bool = False):
    safe_name = sheet_name[:31]
    spreadsheet_safe_dataframe(df).to_excel(writer, index=index, sheet_name=safe_name)
    worksheet = writer.sheets[safe_name]
    worksheet.freeze_panes = "A2"
    if len(df.columns) > 0:
        header_fill = PatternFill("solid", fgColor="1F4E78")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in worksheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        worksheet.auto_filter.ref = worksheet.dimensions
        for column_cells in worksheet.columns:
            header = str(column_cells[0].value or "")
            sample = [str(cell.value or "") for cell in column_cells[1:25]]
            width = min(max([len(header), *[len(x) for x in sample], 10]) + 2, 42)
            worksheet.column_dimensions[column_cells[0].column_letter].width = width
            if any(token in header.lower() for token in ["rate", "ratio", "share"]):
                for cell in column_cells[1:]:
                    cell.number_format = "0.00%"
            elif any(token in header.lower() for token in ["amount", "volume"]):
                for cell in column_cells[1:]:
                    cell.number_format = "#,##0.00"
            elif any(token in header.lower() for token in ["transactions", "hits", "alerts", "cards", "emails", "merchants", "mids"]):
                for cell in column_cells[1:]:
                    cell.number_format = "#,##0"


def _summary_table(df: pd.DataFrame, group_cols: list[str], amount_col: str = "amount") -> pd.DataFrame:
    if df.empty or not all(c in df.columns for c in group_cols):
        return pd.DataFrame()
    agg_spec = {"transaction_id": "count"}
    if amount_col in df.columns:
        agg_spec[amount_col] = "sum"
    out = (
        df.groupby(group_cols, dropna=False)
        .agg(agg_spec)
        .reset_index()
        .rename(columns={"transaction_id": "transaction_count", amount_col: "amount_sum"})
        .sort_values("transaction_count", ascending=False)
    )
    return out


def _success_decline_masks(tx: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    status = tx["status_l"] if "status_l" in tx else tx.get("status", pd.Series("", index=tx.index)).astype(str).str.lower()
    success = status.isin({"success", "approved", "captured", "settled"})
    decline = status.isin({"fail", "failed", "declined", "rejected"})
    return success, decline


def _with_alert_metrics(tx: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    out = tx.copy()
    out["risk_score"] = pd.to_numeric(out.get("risk_score", 0), errors="coerce").fillna(0)
    out["is_flagged"] = out["risk_score"] > 0
    if alerts.empty or "transaction_id" not in alerts.columns:
        out["alert_hits"] = 0
        out["high_critical_alerts"] = 0
        out["scenario_count"] = 0
        return out
    alert_tx = alerts.groupby("transaction_id", dropna=False).agg(
        alert_hits=("rule", "count"),
        scenario_count=("rule", "nunique"),
        high_critical_alerts=("severity", lambda ss: int(ss.isin(["High", "Critical"]).sum())),
    ).reset_index()
    out = out.merge(alert_tx, on="transaction_id", how="left")
    for col in ["alert_hits", "high_critical_alerts", "scenario_count"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int)
    return out


def _risk_pivot(tx: pd.DataFrame, group_cols: list[str], alerts: pd.DataFrame | None = None) -> pd.DataFrame:
    if tx.empty or not all(c in tx.columns for c in group_cols):
        return pd.DataFrame()
    base = _with_alert_metrics(tx, alerts if alerts is not None else pd.DataFrame())
    success, decline = _success_decline_masks(base)
    base = base.assign(
        approved_transaction=success.astype(int),
        declined_transaction=decline.astype(int),
        approved_amount=base["amount"].where(success, 0),
        declined_amount=base["amount"].where(decline, 0),
        flagged_transaction=base["is_flagged"].astype(int),
        high_risk_transaction=base.get("risk_level", "").astype(str).isin(["High", "Critical"]).astype(int),
    )
    out = base.groupby(group_cols, dropna=False).agg(
        total_transactions=("transaction_id", "count"),
        total_amount=("amount", "sum"),
        approved_transactions=("approved_transaction", "sum"),
        approved_amount=("approved_amount", "sum"),
        declined_transactions=("declined_transaction", "sum"),
        declined_amount=("declined_amount", "sum"),
        unique_cards=("card_hash", "nunique"),
        unique_emails=("payer_email", lambda ss: ss[ss.astype(str) != ""].nunique()),
        flagged_transactions=("flagged_transaction", "sum"),
        high_risk_transactions=("high_risk_transaction", "sum"),
        alert_hits=("alert_hits", "sum"),
        high_critical_alerts=("high_critical_alerts", "sum"),
        avg_risk_score=("risk_score", "mean"),
        max_risk_score=("risk_score", "max"),
    ).reset_index()
    out["approval_rate"] = (out["approved_transactions"] / out["total_transactions"]).fillna(0)
    out["decline_rate"] = (out["declined_transactions"] / out["total_transactions"]).fillna(0)
    out["flagged_rate"] = (out["flagged_transactions"] / out["total_transactions"]).fillna(0)
    out["alerts_per_100_trx"] = ((out["alert_hits"] / out["total_transactions"]) * 100).fillna(0)
    ordered = group_cols + [
        "total_transactions", "total_amount", "approved_transactions", "approval_rate",
        "declined_transactions", "decline_rate", "flagged_transactions", "flagged_rate",
        "alert_hits", "alerts_per_100_trx", "high_critical_alerts", "high_risk_transactions",
        "unique_cards", "unique_emails", "avg_risk_score", "max_risk_score",
        "approved_amount", "declined_amount",
    ]
    return out[ordered].sort_values(["high_critical_alerts", "alert_hits", "total_amount"], ascending=[False, False, False])


def _executive_story(tx: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    success, decline = _success_decline_masks(tx)
    total = len(tx)
    alert_hits = len(alerts)
    flagged = int((pd.to_numeric(tx.get("risk_score", 0), errors="coerce").fillna(0) > 0).sum())
    high_critical = int(alerts[alerts["severity"].isin(["High", "Critical"])].shape[0]) if not alerts.empty else 0
    top_rule = alerts["rule"].value_counts().idxmax() if not alerts.empty else ""
    top_merchant = ""
    merchant_pivot = _risk_pivot(tx, ["merchant", "mid"], alerts)
    if not merchant_pivot.empty:
        top = merchant_pivot.iloc[0]
        top_merchant = f"{top['merchant']} / {top['mid']}"
    rows = [
        ("1. Portfolio health", "Total transactions", total, "Baseline activity under review."),
        ("1. Portfolio health", "Total amount", float(tx["amount"].sum()) if "amount" in tx else 0, "Monetary exposure in the file."),
        ("1. Portfolio health", "Approval rate", float(success.sum() / total) if total else 0, "Payment performance signal."),
        ("1. Portfolio health", "Decline rate", float(decline.sum() / total) if total else 0, "Friction, attack, or control signal."),
        ("2. Alert load", "Flagged transactions", flagged, "Transactions requiring analyst attention."),
        ("2. Alert load", "Rule hits", alert_hits, "Raw scenario hits; one transaction can trigger several rules."),
        ("2. Alert load", "High/Critical hits", high_critical, "Priority review queue."),
        ("3. Concentration", "Highest risk merchant/MID", top_merchant, "First place to review concentration and false-positive quality."),
        ("4. Scenario driver", "Top triggered rule", top_rule, "Most common monitoring scenario in this run."),
    ]
    return pd.DataFrame(rows, columns=["story_stage", "metric", "value", "why_it_matters"])


def _period_story(tx: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for period_col in ["transaction_day", "transaction_week", "transaction_month"]:
        if period_col not in tx.columns:
            continue
        table = _risk_pivot(tx, [period_col], alerts)
        if table.empty:
            continue
        table.insert(0, "period_type", period_col.replace("transaction_", "").upper())
        table = table.rename(columns={period_col: "period"})
        frames.append(table)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _scenario_heatmap(alerts: pd.DataFrame) -> pd.DataFrame:
    if alerts.empty:
        return pd.DataFrame()
    out = alerts.groupby(["rule", "severity"], dropna=False).agg(
        alert_hits=("transaction_id", "count"),
        impacted_transactions=("transaction_id", "nunique"),
        impacted_merchants=("merchant", "nunique"),
        impacted_mids=("mid", "nunique"),
        total_amount=("amount", "sum"),
        avg_amount=("amount", "mean"),
        max_observed_value=("observed_value", "max"),
    ).reset_index()
    out["severity_rank"] = out["severity"].map({"Critical": 4, "High": 3, "Medium": 2, "Low": 1}).fillna(0)
    return out.sort_values(["severity_rank", "alert_hits", "total_amount"], ascending=[False, False, False]).drop(columns=["severity_rank"])


def _status_funnel(tx: pd.DataFrame) -> pd.DataFrame:
    if tx.empty or not {"type", "status", "transaction_id", "amount"}.issubset(tx.columns):
        return pd.DataFrame()
    out = tx.groupby(["type", "status"], dropna=False).agg(
        transactions=("transaction_id", "count"),
        amount=("amount", "sum"),
        merchants=("merchant", "nunique"),
        mids=("mid", "nunique"),
    ).reset_index()
    type_totals = out.groupby("type")["transactions"].transform("sum")
    out["share_of_type"] = (out["transactions"] / type_totals).fillna(0)
    return out.sort_values(["type", "transactions"], ascending=[True, False])


def _card_concentration(tx: pd.DataFrame, alerts: pd.DataFrame) -> pd.DataFrame:
    if tx.empty or "card_hash" not in tx.columns:
        return pd.DataFrame()
    base = tx[(tx["card_hash"] != "")].copy()
    if base.empty:
        return pd.DataFrame()
    table = _risk_pivot(base, ["card_display", "card_hash"], alerts)
    if table.empty:
        return table
    extra = base.groupby(["card_display", "card_hash"], dropna=False).agg(
        merchants=("merchant", "nunique"),
        mids=("mid", "nunique"),
        countries=("payer_country", "nunique"),
        first_seen=("transaction_date", "min"),
        last_seen=("transaction_date", "max"),
    ).reset_index()
    return table.merge(extra, on=["card_display", "card_hash"], how="left").sort_values(
        ["alert_hits", "total_transactions", "total_amount"], ascending=[False, False, False]
    )


def _approval_ratio(tx: pd.DataFrame) -> pd.DataFrame:
    if tx.empty or not {"merchant", "mid", "status_l", "amount"}.issubset(tx.columns):
        return pd.DataFrame()
    status = tx["status_l"]
    success_mask = status.isin({"success", "approved", "captured", "settled"})
    out = (
        tx.assign(success_count=success_mask.astype(int), total_count=1)
        .groupby(["merchant", "mid"], dropna=False)
        .agg(
            total_transactions=("total_count", "sum"),
            successful_transactions=("success_count", "sum"),
            total_amount=("amount", "sum"),
        )
        .reset_index()
    )
    out["approval_ratio"] = (out["successful_transactions"] / out["total_transactions"]).fillna(0)
    return out.sort_values(["approval_ratio", "total_transactions"], ascending=[True, False])


def _aml_tm_coverage(alerts: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("Velocity", "Rapid/repeated activity", "CARD_APPROVED_VELOCITY; CARD_DECLINE_VELOCITY; DECLINE_THEN_APPROVAL; REPEATED_CARD_AMOUNT"),
        ("Merchant behaviour", "Static and baseline volume monitoring", "MERCHANT_DAILY_VOLUME; MERCHANT_VOLUME_BASELINE_SPIKE; MERCHANT_APPROVAL_RATE_DROP"),
        ("Customer linkage", "Shared identifiers across cards/accounts", "EMAIL_USED_WITH_MULTIPLE_CARDS; PHONE_USED_WITH_MULTIPLE_CARDS"),
        ("Cross-merchant", "Portfolio instrument linkage", "CARD_USED_ACROSS_MERCHANTS"),
        ("Geography", "Jurisdiction and location inconsistency", "HIGH_RISK_COUNTRY; PAYER_COUNTRY_GEOIP_MISMATCH"),
        ("Refunds", "Refund and reversal behaviour", "MERCHANT_REFUND_RATE_SPIKE"),
        ("Dormancy", "Inactive MID resumption", "DORMANT_MID_RESUMPTION"),
        ("Screening", "Internal watchlist indicators", "WATCHLIST_EMAIL; WATCHLIST_PHONE; WATCHLIST_CARD; WATCHLIST_BIN"),
    ]
    coverage = pd.DataFrame(rows, columns=["tm_area", "aml_tm_rationale", "rules"])
    if alerts.empty:
        coverage["alert_hits"] = 0
        coverage["high_critical_hits"] = 0
        return coverage
    coverage["alert_hits"] = coverage["rules"].apply(
        lambda codes: int(alerts["rule"].isin([c.strip() for c in codes.split(";")]).sum())
    )
    coverage["high_critical_hits"] = coverage["rules"].apply(
        lambda codes: int(
            alerts[
                alerts["rule"].isin([c.strip() for c in codes.split(";")])
                & alerts["severity"].isin(["High", "Critical"])
            ].shape[0]
        )
    )
    return coverage


def make_excel_report(tx: pd.DataFrame, alerts: pd.DataFrame, cases: pd.DataFrame | None = None, rules: dict | None = None) -> bytes:
    cases = cases if cases is not None else build_alert_cases(tx, alerts)
    rules = rules or {"rule_catalog": []}
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        report_tables = [
            ("Executive Story", _executive_story(tx, alerts)),
            ("Portfolio Trend", _period_story(tx, alerts)),
            ("Status Funnel", _status_funnel(tx)),
            ("Merchant Risk Ranking", _risk_pivot(tx, ["merchant", "mid"], alerts)),
            ("MID Brand Risk", _risk_pivot(tx, ["mid", "brand"], alerts)),
            ("Country Corridor Risk", _risk_pivot(tx, ["payer_country", "issuer_country"], alerts)),
            ("Issuer Risk Ranking", _risk_pivot(tx, ["issuer_country", "issuer"], alerts)),
            ("Card Concentration", _card_concentration(tx, alerts).head(1000)),
            ("AML Scenario Heatmap", _scenario_heatmap(alerts)),
            ("AML TM Coverage", _aml_tm_coverage(alerts)),
            ("Decline Reasons", _summary_table(tx[tx["status_l"].isin({"fail", "failed", "declined", "rejected"})] if "status_l" in tx else tx, ["mid", "decline_reason"])),
            ("Approval Ratios", _approval_ratio(tx)),
            ("Data Quality", data_quality_report(tx)),
            ("Rule Performance", rule_performance(alerts, cases, len(tx), rules)),
        ]
        for sheet_name, table in report_tables:
            if not table.empty:
                _write_sheet(writer, table.head(50000), sheet_name)

        successful = tx[tx["status_l"].isin({"success", "approved", "captured", "settled"})].sort_values("amount", ascending=False) if "status_l" in tx else tx.sort_values("amount", ascending=False)
        declined = tx[tx["status_l"].isin({"fail", "failed", "declined", "rejected"})].sort_values("amount", ascending=False) if "status_l" in tx else pd.DataFrame()
        _write_sheet(writer, successful.head(1000), "Top Successful Trx")
        if not declined.empty:
            _write_sheet(writer, declined.head(1000), "Top Declined Trx")
        if not cases.empty:
            _write_sheet(writer, cases, "Investigation Alerts")
        _write_sheet(writer, tx[tx["risk_score"] > 0].sort_values("risk_score", ascending=False), "Flagged Transactions")
        _write_sheet(writer, alerts, "Rule Hits")
        _write_sheet(writer, tx, "Normalized Transactions")
    return output.getvalue()
