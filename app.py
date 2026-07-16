from __future__ import annotations

import copy
import base64
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from transaction_monitor import (
    build_alert_cases,
    data_quality_report,
    effective_limits,
    infer_column_map,
    normalize_transactions,
    evaluate,
    load_rules,
    make_excel_report,
    read_upload,
    rule_performance,
    save_to_sqlite,
    simulate_rule_change,
    spreadsheet_safe_dataframe,
    validate_upload,
)

APP_DIR = Path(__file__).parent
RULES_PATH = APP_DIR / "rules.yaml"
MASCOT_PATH = APP_DIR / "assets" / "payouts_mascot.png"
SAMPLE_PATH = APP_DIR / "sample_data" / "synthetic_transactions.csv"


def env_flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


PUBLIC_DEMO = env_flag("PAYOUTS_TM_PUBLIC_DEMO", True)
HISTORY_ENABLED = env_flag("PAYOUTS_TM_ENABLE_HISTORY", False) and not PUBLIC_DEMO
MAX_UPLOAD_MB = int(os.getenv("PAYOUTS_TM_MAX_UPLOAD_MB", "25"))
MAX_UPLOAD_ROWS = int(os.getenv("PAYOUTS_TM_MAX_UPLOAD_ROWS", "100000"))

st.set_page_config(page_title="Payouts TM Workbench", layout="wide", initial_sidebar_state="expanded")

if MASCOT_PATH.exists():
    mascot_mime = "image/png"
    mascot_data = base64.b64encode(MASCOT_PATH.read_bytes()).decode("ascii")
    mascot_background = f'url("data:{mascot_mime};base64,{mascot_data}")'
else:
    mascot_background = "none"

theme_css = """
<style>
html, body, .stApp, [data-testid="stAppViewContainer"] {
    color:#102A56;
}
.stApp, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 12% 8%, rgba(255,255,255,.98) 0, rgba(255,255,255,.62) 24%, transparent 48%),
        radial-gradient(circle at 88% 82%, rgba(221,52,148,.20) 0, rgba(221,52,148,.08) 27%, transparent 54%),
        radial-gradient(circle at 68% 18%, rgba(29,142,245,.24) 0, rgba(29,142,245,.08) 34%, transparent 60%),
        linear-gradient(135deg, #F8FBFF 0%, #EAF4FF 37%, #EEF0FF 63%, #FBEAF5 100%);
    background-attachment:fixed;
}
[data-testid="stAppViewContainer"]::before {
    content:"";
    position:fixed;
    inset:0;
    pointer-events:none;
    z-index:0;
    background-image:__MASCOT_BACKGROUND__;
    background-repeat:no-repeat;
    background-position:right -4vw bottom -8vh;
    background-size:min(48vw, 680px) auto;
    opacity:.16;
    filter:saturate(1.08) contrast(.98);
    -webkit-mask-image:radial-gradient(ellipse 62% 70% at 76% 70%, #000 25%, rgba(0,0,0,.76) 50%, transparent 82%);
    mask-image:radial-gradient(ellipse 62% 70% at 76% 70%, #000 25%, rgba(0,0,0,.76) 50%, transparent 82%);
}
[data-testid="stAppViewContainer"] > * {position:relative; z-index:1;}
header[data-testid="stHeader"] {background:rgba(248,251,255,.58); backdrop-filter:blur(14px);}
.block-container {padding-top:1.1rem; padding-bottom:2rem;}
[data-testid="stSidebar"] {
    background:
        radial-gradient(circle at 20% 12%, rgba(255,255,255,.92), transparent 42%),
        linear-gradient(165deg, rgba(228,244,255,.97) 0%, rgba(221,235,255,.96) 55%, rgba(246,220,239,.96) 100%);
    border-right:1px solid rgba(57,105,178,.18);
    box-shadow:10px 0 32px rgba(30,77,140,.08);
}
[data-testid="stSidebar"] * {color:#15355F;}
[data-testid="stSidebar"] [data-baseweb="radio"] label:hover {
    background:rgba(255,255,255,.42);
    border-radius:10px;
}
.tm-card {
    border:1px solid rgba(106,146,199,.22);
    padding:16px;
    border-radius:14px;
    background:rgba(255,255,255,.76);
    box-shadow:0 12px 32px rgba(30,75,138,.09);
    backdrop-filter:blur(16px);
}
.tm-small {font-size:0.86rem; color:#536987;}
.badge {padding:3px 9px; border-radius:999px; background:#EDF2FF; color:#1B4DBA; font-size:.78rem;}
.severity-critical {background:#7F1D1D;color:white}.severity-high {background:#B91C1C;color:white}
.severity-medium {background:#B45309;color:white}.severity-low {background:#1D4ED8;color:white}
div[data-testid="stDataFrame"], div[data-testid="stTable"],
div[data-testid="stExpander"], div[data-testid="stFileUploader"] {
    border-radius:14px;
    background:rgba(255,255,255,.70);
    backdrop-filter:blur(14px);
}
.stTextInput input, .stNumberInput input, .stTextArea textarea,
div[data-baseweb="select"] > div {
    background:rgba(255,255,255,.84) !important;
    color:#102A56 !important;
    border-color:rgba(73,117,179,.25) !important;
}
@media (max-width:900px) {
    [data-testid="stAppViewContainer"]::before {
        background-size:76vw auto;
        background-position:right -24vw bottom -4vh;
        opacity:.09;
    }
}
</style>
"""
st.markdown(theme_css.replace("__MASCOT_BACKGROUND__", mascot_background), unsafe_allow_html=True)


def load_default_rules() -> dict:
    return load_rules(RULES_PATH)


def csv_list(text: str) -> list[str]:
    return [x.strip() for x in str(text or "").split(",") if x.strip()]


def detailed_rules_to_rows(rules: dict, section: str) -> list[dict]:
    rows = []
    for entity, config in (rules.get(section) or {}).items():
        actual = config.get("actual_value") or {}
        merchant_value = config.get("merchant_value") or {}
        for brand, brand_rules in (config.get("brand_rules") or {"all": {}}).items():
            rows.append({
                "entity": entity,
                "brand": brand,
                "successful_limit": brand_rules.get("successful_limit"),
                "successful_window_hours": brand_rules.get("successful_window_hours"),
                "failed_limit": brand_rules.get("failed_limit"),
                "failed_window_hours": brand_rules.get("failed_window_hours"),
                "daily_volume_limit": brand_rules.get("daily_volume_limit"),
                "actual_min": actual.get("min"),
                "actual_max": actual.get("max"),
                "merchant_min": merchant_value.get("min"),
                "merchant_max": merchant_value.get("max"),
            })
    return rows


def rows_to_detailed_rules(rows: pd.DataFrame) -> dict:
    out = {}
    if rows is None or rows.empty:
        return out
    for _, row in rows.dropna(subset=["entity"]).iterrows():
        entity = str(row["entity"]).strip()
        if not entity:
            continue
        brand = str(row.get("brand") or "all").strip().lower() or "all"
        config = out.setdefault(entity, {"brand_rules": {}, "actual_value": {}, "merchant_value": {}})
        config["brand_rules"][brand] = {
            k: row[k] for k in ["successful_limit", "successful_window_hours", "failed_limit", "failed_window_hours", "daily_volume_limit"]
            if k in row and pd.notna(row[k])
        }
        if pd.notna(row.get("actual_min")):
            config["actual_value"]["min"] = row["actual_min"]
        if pd.notna(row.get("actual_max")):
            config["actual_value"]["max"] = row["actual_max"]
        if pd.notna(row.get("merchant_min")):
            config["merchant_value"]["min"] = row["merchant_min"]
        if pd.notna(row.get("merchant_max")):
            config["merchant_value"]["max"] = row["merchant_max"]
    return out


def init_state():
    defaults = load_default_rules()
    st.session_state.setdefault("rules", defaults)
    st.session_state.setdefault("current_rules", copy.deepcopy(defaults))
    st.session_state.setdefault("raw_df", None)
    st.session_state.setdefault("tx", None)
    st.session_state.setdefault("alerts", None)
    st.session_state.setdefault("cases", None)
    st.session_state.setdefault("simulation", None)
    st.session_state.setdefault("simulation_affected", None)
    st.session_state.setdefault("column_map", {})
    st.session_state.setdefault("uploaded_name", "")
    st.session_state.setdefault("uploaded_identity", "")
    st.session_state.setdefault("privacy_ack", False)


def set_uploaded_data(raw: pd.DataFrame, name: str, identity: str) -> None:
    st.session_state.raw_df = raw
    st.session_state.uploaded_name = name
    st.session_state.uploaded_identity = identity
    st.session_state.column_map = infer_column_map(raw)
    st.session_state.tx = None
    st.session_state.alerts = None
    st.session_state.cases = None
    st.session_state.simulation = None
    st.session_state.simulation_affected = None


def clear_loaded_data() -> None:
    for key, default in {
        "raw_df": None,
        "tx": None,
        "alerts": None,
        "cases": None,
        "simulation": None,
        "simulation_affected": None,
        "column_map": {},
        "uploaded_name": "",
        "uploaded_identity": "",
    }.items():
        st.session_state[key] = default
    st.cache_data.clear()


def csv_download_bytes(df: pd.DataFrame) -> bytes:
    return spreadsheet_safe_dataframe(df).to_csv(index=False).encode("utf-8")


def kpi(label, value, note=""):
    st.markdown(f"<div class='tm-card'><div class='tm-small'>{label}</div><h2 style='margin:.2rem 0'>{value}</h2><div class='tm-small'>{note}</div></div>", unsafe_allow_html=True)


def severity_badge(severity: str) -> str:
    value = str(severity or "Low")
    return f"<span class='badge severity-{value.lower()}'>{value}</span>"


@st.cache_data(show_spinner=False, ttl=900, max_entries=2)
def cached_evaluate(tx: pd.DataFrame, rules: dict):
    return evaluate(tx, rules)


@st.cache_data(show_spinner=False, ttl=900, max_entries=2)
def cached_report(tx: pd.DataFrame, alerts: pd.DataFrame, cases: pd.DataFrame, rules: dict):
    return make_excel_report(tx, alerts, cases, rules)


def sidebar():
    st.sidebar.markdown("### PAYOUTS")
    st.sidebar.caption("Transaction Monitoring Workbench")
    if PUBLIC_DEMO:
        st.sidebar.info("Public demo · synthetic data only")
    page = st.sidebar.radio(
        "Navigation",
        ["Dashboard", "Transaction Explorer", "Monitoring Run", "Alert Queue", "Merchant Behaviour", "MID Behaviour", "Rule Performance", "Rule Builder", "Rule Plans", "Behavior Search", "Reports", "Configuration"],
        index=2,
    )
    st.sidebar.divider()
    st.sidebar.markdown("#### TM Toggles")
    st.session_state["toggle_velocity"] = st.sidebar.toggle("Velocity rules", True)
    st.session_state["toggle_geo"] = st.sidebar.toggle("Geo / country rules", True)
    st.session_state["toggle_identity"] = st.sidebar.toggle("Email / phone linkage", True)
    st.session_state["toggle_pattern"] = st.sidebar.toggle("Repeated pattern rules", True)
    st.session_state["toggle_watchlist"] = st.sidebar.toggle("Watchlist rules", True)
    st.session_state["toggle_baseline"] = st.sidebar.toggle("Baseline rules", True)
    st.sidebar.caption("Toggles control rule visibility and the working config for this Streamlit session.")
    st.sidebar.divider()
    if st.sidebar.button("Clear loaded data and cache", use_container_width=True):
        clear_loaded_data()
        st.sidebar.success("Session data and cached results cleared.")
    return page


def upload_and_map():
    st.subheader("1. Upload transaction file")
    if PUBLIC_DEMO:
        st.warning(
            "Public demonstration environment: use synthetic or fully anonymized data only. "
            "Do not upload live cardholder, personal, merchant-confidential, or production transaction data."
        )

    load_demo = st.button("Load bundled synthetic demo", use_container_width=False)
    if load_demo:
        try:
            raw = pd.read_csv(SAMPLE_PATH)
            set_uploaded_data(raw, SAMPLE_PATH.name, f"sample:{SAMPLE_PATH.stat().st_mtime_ns}")
            st.success(f"Loaded synthetic demo: {len(raw):,} rows, {len(raw.columns):,} columns")
        except Exception as exc:
            st.error(f"The bundled demo data could not be loaded: {exc}")

    upload_allowed = True
    if PUBLIC_DEMO:
        upload_allowed = st.checkbox(
            "I confirm this file contains only synthetic or fully anonymized data.",
            key="privacy_ack",
        )

    up = st.file_uploader(
        "Upload CSV / XLS / XLSX",
        type=["csv", "xls", "xlsx"],
        disabled=not upload_allowed,
        help=f"Maximum {MAX_UPLOAD_MB} MB and {MAX_UPLOAD_ROWS:,} rows.",
    )
    if up:
        upload_size = int(getattr(up, "size", 0) or 0)
        identity = f"{up.name}:{upload_size}:{getattr(up, 'file_id', '')}"
        if upload_size > MAX_UPLOAD_MB * 1024 * 1024:
            st.error(f"Upload rejected: {upload_size / 1024 / 1024:.1f} MB exceeds the {MAX_UPLOAD_MB} MB limit.")
        elif identity != st.session_state.uploaded_identity:
            try:
                raw = read_upload(up)
                if len(raw) > MAX_UPLOAD_ROWS:
                    st.error(f"Upload rejected: {len(raw):,} rows exceed the {MAX_UPLOAD_ROWS:,}-row limit.")
                else:
                    set_uploaded_data(raw, up.name, identity)
                    st.success(f"Loaded {up.name}: {len(raw):,} rows, {len(raw.columns):,} columns")
            except Exception as exc:
                st.error(f"The file could not be read. Confirm its format and integrity. Details: {exc}")

    raw = st.session_state.raw_df
    if raw is None:
        st.info("Load the bundled synthetic demo or upload a file to begin. Column names are inferred automatically.")
        return None

    with st.expander("Column mapping", expanded=False):
        st.caption("Adjust only if a field was not inferred correctly.")
        inferred = st.session_state.column_map or infer_column_map(raw)
        edited = {}
        cols = [""] + list(raw.columns)
        for canonical in [
            "transaction_id", "merchant", "mid", "transaction_date", "type", "status",
            "amount", "merchant_amount", "currency", "brand", "card_number", "payer_name",
            "payer_country", "payer_email", "payer_phone", "geoip_country", "gateway_id",
            "card_type", "card_category", "issuer", "issuer_country", "decline_reason",
            "decline_type",
        ]:
            current = inferred.get(canonical, "")
            edited[canonical] = st.selectbox(canonical, cols, index=cols.index(current) if current in cols else 0, key=f"map_{canonical}")
        st.session_state.column_map = {k: v for k, v in edited.items() if v}

    validation = validate_upload(raw, st.session_state.column_map, MAX_UPLOAD_ROWS)
    if not validation.empty:
        errors = validation[validation["severity"] == "Error"]
        warnings = validation[validation["severity"] == "Warning"]
        if not errors.empty:
            st.error(f"{len(errors)} blocking validation issue(s) must be corrected before monitoring.")
        elif not warnings.empty:
            st.warning(f"{len(warnings)} upload-quality warning(s) should be reviewed.")
        with st.expander("Upload validation details", expanded=not errors.empty):
            st.dataframe(validation, use_container_width=True, hide_index=True)
        if not errors.empty:
            return None

    if st.button("Normalize / Refresh Data", type="primary"):
        st.session_state.tx = normalize_transactions(raw, st.session_state.column_map)
        st.success("Transactions normalized.")

    if st.session_state.tx is None:
        st.session_state.tx = normalize_transactions(raw, st.session_state.column_map)
    return st.session_state.tx


def advanced_filter(df: pd.DataFrame, prefix="explore") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    st.markdown("#### Advanced Search")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        merchant = st.multiselect("Merchant", sorted([x for x in df["merchant"].dropna().unique() if str(x)]), key=f"{prefix}_merchant")
        status = st.multiselect("Status", sorted([x for x in df["status"].dropna().unique() if str(x)]), key=f"{prefix}_status")
    with c2:
        mids = st.multiselect("MID", sorted([x for x in df["mid"].dropna().unique() if str(x)]), key=f"{prefix}_mid")
        brand = st.multiselect("Brand", sorted([x for x in df["brand"].dropna().unique() if str(x)]), key=f"{prefix}_brand")
    with c3:
        min_amt = st.number_input("Min amount", value=0.0, key=f"{prefix}_min")
        max_amt = st.number_input("Max amount", value=float(max(df["amount"].max(), 0)) if "amount" in df else 0.0, key=f"{prefix}_max")
    with c4:
        text = st.text_input("Free text", placeholder="email, card, payment id, country", key=f"{prefix}_text")
        only_flagged = st.checkbox("Flagged only", key=f"{prefix}_flagged") if "risk_score" in df else False
    out = df.copy()
    if merchant: out = out[out["merchant"].isin(merchant)]
    if mids: out = out[out["mid"].isin(mids)]
    if status: out = out[out["status"].isin(status)]
    if brand: out = out[out["brand"].isin(brand)]
    if "amount" in out: out = out[(out["amount"] >= min_amt) & (out["amount"] <= max_amt)]
    if only_flagged: out = out[out.get("risk_score", 0) > 0]
    if text:
        s = out.astype(str).agg(" ".join, axis=1).str.lower()
        out = out[s.str.contains(text.lower(), na=False)]
    return out


def rules_filtered_by_toggles(rules: dict) -> dict:
    rules = copy.deepcopy(rules)
    disabled = set()
    group_map = {
        "Velocity": st.session_state.get("toggle_velocity", True),
        "Geo": st.session_state.get("toggle_geo", True),
        "Identity Linkage": st.session_state.get("toggle_identity", True),
        "Pattern": st.session_state.get("toggle_pattern", True),
        "Watchlist": st.session_state.get("toggle_watchlist", True),
        "Merchant": True,
    }
    for r in rules.get("rule_catalog", []):
        is_baseline = str(r.get("baseline_method", "")).lower().startswith("trailing")
        if not group_map.get(r.get("group"), True) or not r.get("enabled", True) or (is_baseline and not st.session_state.get("toggle_baseline", True)):
            disabled.add(r.get("code"))
    rules["_disabled_rules"] = list(disabled)
    return rules


def run_monitoring(tx: pd.DataFrame | None):
    st.subheader("2. Monitoring Run")
    if tx is None or tx.empty:
        st.warning("Upload transactions first.")
        return
    c1, c2, c3 = st.columns([1,1,2])
    with c1:
        save_history = st.checkbox(
            "Save to SQLite history",
            value=False,
            disabled=not HISTORY_ENABLED,
            help="Disabled in public demo mode. Enable only in a controlled local/private environment.",
        )
    with c2:
        simulator = st.checkbox("Simulator mode", value=False, help="Compare proposed session rules with the current accepted settings on the same upload.")
    with c3:
        history_note = " Local SQLite history is disabled." if not HISTORY_ENABLED else ""
        st.caption(f"Monitoring rules only. Preventive limit breaches remain visible on transactions but do not create TM alerts.{history_note}")
    if st.button("Run Monitoring Engine", type="primary"):
        working_rules = rules_filtered_by_toggles(st.session_state.rules)
        if simulator:
            comparison, affected = simulate_rule_change(tx, st.session_state.current_rules, working_rules)
            st.session_state.simulation = comparison
            st.session_state.simulation_affected = affected
        tx2, alerts = cached_evaluate(tx, working_rules)
        cases = build_alert_cases(tx2, alerts)
        st.session_state.tx = tx2
        st.session_state.alerts = alerts
        st.session_state.cases = cases
        if save_history and not simulator:
            save_to_sqlite(tx2, alerts, APP_DIR / "tm_history.db", cases)
        if not simulator:
            st.session_state.current_rules = copy.deepcopy(working_rules)
        st.success("Simulation complete." if simulator else "Monitoring run complete.")

    tx2, alerts, cases = st.session_state.tx, st.session_state.alerts, st.session_state.cases
    if tx2 is not None and "risk_score" in tx2:
        a = alerts if alerts is not None else pd.DataFrame()
        c = cases if cases is not None else pd.DataFrame()
        k1,k2,k3,k4 = st.columns(4)
        with k1: kpi("Transactions", f"{len(tx2):,}", st.session_state.uploaded_name)
        with k2: kpi("Flagged transactions", f"{int((tx2['risk_score']>0).sum()):,}", f"{(tx2['risk_score']>0).mean():.2%} alert rate")
        with k3: kpi("Investigation alerts", f"{len(c):,}", f"{len(a):,} supporting rule hits")
        with k4: kpi("High + Critical", f"{len(c[c['severity'].isin(['High','Critical'])]) if not c.empty else 0:,}", "consolidated priority queue")
        quality = data_quality_report(tx2)
        warnings = quality[quality["quality_status"] != "Usable"]
        if not warnings.empty:
            st.warning(f"{len(warnings)} data-quality dependencies require attention. Review the Data Quality section below.")
            with st.expander("Data-quality warnings"):
                st.dataframe(warnings, use_container_width=True, hide_index=True)
        if st.session_state.simulation is not None:
            st.markdown("#### Current versus proposed simulation")
            st.dataframe(st.session_state.simulation, use_container_width=True, hide_index=True)
            if st.session_state.simulation_affected is not None and not st.session_state.simulation_affected.empty:
                with st.expander("Top affected merchants and MIDs"):
                    st.dataframe(st.session_state.simulation_affected.head(25), use_container_width=True, hide_index=True)
        if not a.empty:
            st.markdown("#### Top monitoring scenarios")
            s = a.groupby(["rule", "severity"]).size().reset_index(name="hits").sort_values("hits", ascending=False)
            st.dataframe(s, use_container_width=True, hide_index=True)
            with st.expander("Raw rule-hit evidence"):
                st.dataframe(a, use_container_width=True, hide_index=True)


def page_dashboard():
    st.title("Monitoring Run Summary")
    tx, alerts, cases = st.session_state.tx, st.session_state.alerts, st.session_state.cases
    if tx is None:
        st.info("No transactions loaded yet.")
        return
    alerts = alerts if alerts is not None else pd.DataFrame()
    cases = cases if cases is not None else pd.DataFrame()
    flagged = int(tx.get("risk_score", pd.Series(0, index=tx.index)).gt(0).sum())
    k1,k2,k3,k4 = st.columns(4)
    with k1: kpi("Transactions processed", f"{len(tx):,}", st.session_state.uploaded_name)
    with k2: kpi("Transactions flagged", f"{flagged:,}", f"{flagged/max(len(tx),1):.2%} alert rate")
    with k3: kpi("Unique alerts", f"{len(cases):,}", f"{len(alerts):,} rule hits")
    with k4: kpi("High/Critical alerts", f"{len(cases[cases['severity'].isin(['High','Critical'])]) if not cases.empty else 0:,}", "priority investigation")
    if not cases.empty:
        c1, c2 = st.columns(2)
        with c1:
            severity = cases["severity"].value_counts().rename_axis("severity").reset_index(name="alerts")
            st.markdown("#### Severity distribution")
            st.dataframe(severity, use_container_width=True, hide_index=True)
        with c2:
            top_rules = alerts["rule_name"].value_counts().head(10).rename_axis("rule").reset_index(name="hits")
            st.markdown("#### Top triggered rules")
            st.dataframe(top_rules, use_container_width=True, hide_index=True)
        c3, c4 = st.columns(2)
        with c3:
            st.markdown("#### Top affected merchants")
            st.dataframe(cases.groupby("merchant").agg(alerts=("alert_id", "nunique"), max_risk=("risk_score", "max"), amount=("total_amount", "sum")).reset_index().sort_values(["max_risk", "alerts"], ascending=False).head(10), use_container_width=True, hide_index=True)
        with c4:
            st.markdown("#### Top affected MIDs")
            st.dataframe(cases.groupby("mid").agg(alerts=("alert_id", "nunique"), max_risk=("risk_score", "max"), amount=("total_amount", "sum")).reset_index().sort_values(["max_risk", "alerts"], ascending=False).head(10), use_container_width=True, hide_index=True)
    quality = data_quality_report(tx)
    with st.expander("Data-quality warnings"):
        st.dataframe(quality, use_container_width=True, hide_index=True)


def page_explorer():
    st.title("Transaction Explorer")
    tx = upload_and_map()
    if tx is None: return
    out = advanced_filter(tx)
    st.caption(f"Showing {len(out):,} of {len(tx):,} rows")
    st.dataframe(out, use_container_width=True, height=520)


def page_rule_builder():
    st.title("Rule Builder")
    rules = st.session_state.rules
    st.caption("Search governed monitoring rules by name, field, family, entity, plan, severity, status, merchant or MID applicability.")
    q = st.text_input("Search rule catalog", placeholder="velocity, country, card, merchant, plan...")
    catalog = pd.DataFrame(rules.get("rule_catalog", []))
    f1, f2, f3 = st.columns(3)
    with f1:
        families = st.multiselect("Family", sorted(catalog["family"].dropna().unique()) if not catalog.empty else [])
    with f2:
        severities = st.multiselect("Severity", sorted(catalog["severity"].dropna().unique()) if not catalog.empty else [])
    with f3:
        statuses = st.multiselect("Status", ["Enabled", "Disabled"])
    if q and not catalog.empty:
        catalog = catalog[catalog.astype(str).agg(" ".join, axis=1).str.lower().str.contains(q.lower(), na=False)]
    if families:
        catalog = catalog[catalog["family"].isin(families)]
    if severities:
        catalog = catalog[catalog["severity"].isin(severities)]
    if statuses:
        wanted = {value == "Enabled" for value in statuses}
        catalog = catalog[catalog["enabled"].isin(wanted)]
    st.markdown("#### Governed monitoring rule catalogue")
    editable_columns = ["code", "name", "family", "classification", "applicable_entity", "severity", "risk_weight", "enabled"]
    edited = st.data_editor(catalog[[column for column in editable_columns if column in catalog]], use_container_width=True, hide_index=True, num_rows="fixed")
    if st.button("Apply catalog changes"):
        edited_by_code = {row.get("code"): row for row in edited.to_dict("records") if row.get("code")}
        st.session_state.rules["rule_catalog"] = [
            {**row, **edited_by_code.get(row.get("code"), {})} for row in rules.get("rule_catalog", [])
        ]
        st.success("Rule catalog updated in session.")
    if not catalog.empty:
        selected_rule = st.selectbox("Inspect full rule definition", catalog["code"].tolist())
        with st.expander("Full governed definition", expanded=False):
            st.json(next(row for row in rules.get("rule_catalog", []) if row.get("code") == selected_rule))

    with st.expander("Preventive-control catalogue"):
        st.caption("These controls remain visible as transaction context and do not execute in the TM alert engine.")
        st.dataframe(pd.DataFrame(rules.get("preventive_control_catalog", [])), use_container_width=True, hide_index=True)
    with st.expander("Future-data requirements"):
        st.dataframe(pd.DataFrame(rules.get("future_data_requirements", [])), use_container_width=True, hide_index=True)

    st.markdown("#### Global parameters")
    g = rules.setdefault("global", {})
    c1,c2,c3 = st.columns(3)
    with c1:
        g["monitoring_window_hours"] = st.number_input("Monitoring window hours", 1, 720, int(g.get("monitoring_window_hours",24)))
        g["card_approved_count_limit"] = st.number_input("Default approved velocity", 1, 1000, int(g.get("card_approved_count_limit",7)))
    with c2:
        g["card_declined_count_limit"] = st.number_input("Default decline velocity", 1, 1000, int(g.get("card_declined_count_limit",3)))
        g["email_multiple_card_limit"] = st.number_input("Email → multiple cards", 1, 1000, int(g.get("email_multiple_card_limit",2)))
    with c3:
        g["phone_multiple_card_limit"] = st.number_input("Phone → multiple cards", 1, 1000, int(g.get("phone_multiple_card_limit",2)))
        g["min_transaction_amount"] = st.number_input("Preventive minimum amount", 0.0, value=float(g.get("min_transaction_amount",50)))
    g["repeated_amount_window_minutes"] = st.number_input("Repeated amount window minutes", 1, 1440, int(g.get("repeated_amount_window_minutes",10)))
    a1, a2, a3 = st.columns(3)
    with a1:
        g["cross_merchant_card_limit"] = st.number_input("Cross-merchant card limit", 2, 100, int(g.get("cross_merchant_card_limit", 3)))
        g["dormant_mid_days"] = st.number_input("Dormant MID days", 7, 730, int(g.get("dormant_mid_days", 30)))
    with a2:
        g["decline_then_approval_limit"] = st.number_input("Declines before approval", 1, 100, int(g.get("decline_then_approval_limit", 2)))
        g["merchant_volume_baseline_multiplier"] = st.number_input("Volume baseline multiplier", 1.1, 20.0, float(g.get("merchant_volume_baseline_multiplier", 3.5)), step=0.1)
    with a3:
        g["approval_rate_drop_points"] = st.number_input("Approval-rate drop", 0.01, 1.0, float(g.get("approval_rate_drop_points", 0.30)), step=0.01)
        g["refund_rate_baseline_multiplier"] = st.number_input("Refund baseline multiplier", 1.1, 20.0, float(g.get("refund_rate_baseline_multiplier", 3.0)), step=0.1)
    countries = st.text_area("High-risk countries / codes", value=", ".join(g.get("high_risk_countries", [])))
    g["high_risk_countries"] = csv_list(countries)


def page_rule_plans():
    st.title("Rule Plans & Overrides")
    st.caption("Use plans for general, gaming, forex, VIP, high-risk or merchant-specific antifraud setups.")
    rules = st.session_state.rules
    plans_df = pd.DataFrame([{"plan": k, **v} for k,v in rules.get("plans", {}).items()])
    edited = st.data_editor(plans_df, use_container_width=True, hide_index=True, num_rows="dynamic", key="plan_matrix")
    if st.button("Apply plan matrix"):
        new = {}
        for _, row in edited.dropna(subset=["plan"]).iterrows():
            d = row.drop(labels=["plan"]).dropna().to_dict()
            new[str(row["plan"]).strip().upper()] = d
        st.session_state.rules["plans"] = new
        st.success("Plan matrix updated.")

    st.markdown("#### MID rule matrix")
    mid_columns = ["entity", "brand", "successful_limit", "successful_window_hours", "failed_limit", "failed_window_hours", "daily_volume_limit", "actual_min", "actual_max", "merchant_min", "merchant_max"]
    mid_rows = pd.DataFrame(detailed_rules_to_rows(rules, "mid_rules"))
    if mid_rows.empty:
        mid_rows = pd.DataFrame(columns=mid_columns)
    mid_edited = st.data_editor(mid_rows, use_container_width=True, hide_index=True, num_rows="dynamic", key="mid_rule_matrix")
    if st.button("Apply MID rule matrix"):
        st.session_state.rules["mid_rules"] = rows_to_detailed_rules(mid_edited)
        st.success("MID rules updated.")

    st.markdown("#### Merchant rule matrix")
    merchant_rows = pd.DataFrame(detailed_rules_to_rows(rules, "merchant_rules"))
    if merchant_rows.empty:
        merchant_rows = pd.DataFrame(columns=mid_columns)
    merchant_edited = st.data_editor(merchant_rows, use_container_width=True, hide_index=True, num_rows="dynamic", key="merchant_rule_matrix")
    if st.button("Apply merchant rule matrix"):
        st.session_state.rules["merchant_rules"] = rows_to_detailed_rules(merchant_edited)
        st.success("Merchant rules updated.")

    c1,c2 = st.columns(2)
    with c1:
        st.markdown("#### Merchant → Plan map")
        txt = st.text_area("YAML", yaml.safe_dump(rules.get("merchant_plan_map", {}), sort_keys=False), height=160, key="merchant_map_yaml")
    with c2:
        st.markdown("#### MID → Plan map")
        txt2 = st.text_area("YAML", yaml.safe_dump(rules.get("mid_plan_map", {}), sort_keys=False), height=160, key="mid_map_yaml")
    c3,c4 = st.columns(2)
    with c3:
        st.markdown("#### Merchant overrides")
        txt3 = st.text_area("YAML", yaml.safe_dump(rules.get("merchant_overrides", {}), sort_keys=False), height=180, key="merchant_overrides_yaml")
    with c4:
        st.markdown("#### MID overrides")
        txt4 = st.text_area("YAML", yaml.safe_dump(rules.get("mid_overrides", {}), sort_keys=False), height=180, key="mid_overrides_yaml")
    if st.button("Apply YAML mappings/overrides"):
        try:
            rules["merchant_plan_map"] = yaml.safe_load(txt) or {}
            rules["mid_plan_map"] = yaml.safe_load(txt2) or {}
            rules["merchant_overrides"] = yaml.safe_load(txt3) or {}
            rules["mid_overrides"] = yaml.safe_load(txt4) or {}
            st.success("Mappings and overrides updated.")
        except Exception as e:
            st.error(f"Invalid YAML: {e}")

    st.markdown("#### Temporary overrides")
    st.caption("Temporary overrides are the most specific layer and apply only during their valid start/expiry period.")
    temporary = pd.DataFrame(rules.get("temporary_overrides", []))
    if temporary.empty:
        temporary = pd.DataFrame(columns=["id", "merchant", "mid", "starts_at", "expires_at", "enabled", "reason", "approved_by", "values_yaml"])
    else:
        temporary["values_yaml"] = temporary.get("values", pd.Series([{}] * len(temporary))).apply(lambda value: yaml.safe_dump(value or {}, default_flow_style=True).strip())
        temporary = temporary.drop(columns="values", errors="ignore")
    temporary_edited = st.data_editor(temporary, use_container_width=True, hide_index=True, num_rows="dynamic", key="temporary_overrides")
    if st.button("Apply temporary overrides"):
        try:
            records = temporary_edited.dropna(how="all").to_dict("records")
            for record in records:
                record["values"] = yaml.safe_load(record.pop("values_yaml", "{}")) or {}
            st.session_state.rules["temporary_overrides"] = records
            st.success("Temporary overrides updated for this session.")
        except Exception as exc:
            st.error(f"Invalid temporary override values: {exc}")

    st.markdown("#### Baseline settings")
    baseline = rules.setdefault("baseline_settings", {})
    b1, b2 = st.columns(2)
    with b1:
        baseline["lookback_days"] = st.number_input("Trailing lookback days", 7, 180, int(baseline.get("lookback_days", 30)))
    with b2:
        baseline["minimum_history_days"] = st.number_input("Minimum history days", 2, 90, int(baseline.get("minimum_history_days", 7)))
    st.caption("These are deterministic trailing averages, not machine learning.")


def page_behavior_search():
    st.title("Behavior Search")
    tx = st.session_state.tx
    if tx is None:
        st.info("Load transactions first.")
        return
    st.caption("Search for behaviours, not just transactions.")
    mode = st.selectbox("Find", ["Cards used by many emails", "Emails used with many cards", "Phones used with many cards", "Cards across merchants", "Repeated exact amount"])
    threshold = st.number_input("Minimum count", min_value=2, value=3)
    if mode == "Cards used by many emails":
        base = tx[(tx["card_hash"] != "") & (tx["payer_email"] != "")]
        res = base.groupby(["card_display", "card_hash"]).agg(count=("payer_email","nunique"), merchants=("merchant","nunique"), volume=("amount","sum")).reset_index()
    elif mode == "Emails used with many cards":
        base = tx[(tx["payer_email"] != "") & (tx["card_hash"] != "")]
        res = base.groupby("payer_email").agg(count=("card_hash","nunique"), merchants=("merchant","nunique"), volume=("amount","sum")).reset_index()
    elif mode == "Phones used with many cards":
        base = tx[(tx["payer_phone"] != "") & (tx["card_hash"] != "")]
        res = base.groupby("payer_phone").agg(count=("card_hash","nunique"), merchants=("merchant","nunique"), volume=("amount","sum")).reset_index()
    elif mode == "Cards across merchants":
        base = tx[tx["card_hash"] != ""]
        res = base.groupby(["card_display", "card_hash"]).agg(count=("merchant","nunique"), transactions=("transaction_id","count"), volume=("amount","sum")).reset_index()
    else:
        base = tx[(tx["card_hash"] != "") & (tx["amount"] > 0)]
        res = base.groupby(["merchant", "card_display", "amount"]).agg(count=("transaction_id","count"), volume=("amount","sum")).reset_index()
    res = res[res["count"] >= threshold].sort_values("count", ascending=False)
    st.dataframe(res, use_container_width=True, hide_index=True)


def page_alerts():
    st.title("Alert Queue")
    alerts, cases, tx = st.session_state.alerts, st.session_state.cases, st.session_state.tx
    if cases is None or cases.empty:
        st.info("No alerts yet. Run monitoring first.")
        return
    q = st.text_input("Search alerts", placeholder="insight, merchant, MID, rule, entity")
    out = cases.copy()
    if q:
        out = out[out.astype(str).agg(" ".join, axis=1).str.lower().str.contains(q.lower(), na=False)]
    f1, f2, f3 = st.columns(3)
    with f1:
        status = st.multiselect("Status", sorted(out["status"].dropna().unique()))
    with f2:
        severity = st.multiselect("Severity", ["Critical", "High", "Medium", "Low"])
    with f3:
        merchant = st.multiselect("Merchant", sorted(out["merchant"].dropna().unique()))
    if status:
        out = out[out["status"].isin(status)]
    if severity:
        out = out[out["severity"].isin(severity)]
    if merchant:
        out = out[out["merchant"].isin(merchant)]
    queue_cols = ["alert_id", "severity", "risk_score", "merchant", "mid", "primary_entity", "investigative_insight", "triggered_rule_count", "transaction_count", "total_amount", "first_activity_time", "last_activity_time", "status"]
    st.dataframe(out[queue_cols], use_container_width=True, height=380, hide_index=True)
    if out.empty:
        return

    selected_id = st.selectbox("Open alert", out["alert_id"].tolist(), format_func=lambda value: f"{value} — {out.loc[out['alert_id'].eq(value), 'investigative_insight'].iloc[0]}")
    case = out[out["alert_id"] == selected_id].iloc[0]
    st.markdown(f"### {case['investigative_insight']} {severity_badge(case['severity'])}", unsafe_allow_html=True)
    st.caption(f"{case['alert_id']} · {case['merchant']} · {case['mid']} · {case['first_activity_time']} to {case['last_activity_time']}")

    st.markdown("#### Key metrics")
    m1, m2, m3, m4 = st.columns(4)
    with m1: kpi("Risk score", f"{int(case['risk_score'])}/100", case["rule_families"])
    with m2: kpi("Transactions", f"{int(case['transaction_count']):,}", f"{int(case['decline_count']):,} declines")
    with m3: kpi("Total amount", f"{float(case['total_amount']):,.2f}", f"approved {float(case['approved_amount']):,.2f}")
    with m4: kpi("Triggered rules", f"{int(case['triggered_rule_count']):,}", str(case["primary_entity"]))

    st.markdown("#### Why flagged")
    for driver in str(case["top_risk_drivers"]).split(" | "):
        if driver:
            st.markdown(f"- {driver}")
    if str(case["baseline_comparison"]).strip():
        st.markdown("#### Behaviour versus baseline")
        st.info(str(case["baseline_comparison"]))

    st.markdown("#### Related indicators")
    r1, r2, r3 = st.columns(3)
    with r1: st.caption(f"Cards: {case['related_cards'] or 'None returned'}")
    with r2: st.caption(f"Emails: {case['related_emails'] or 'None returned'}")
    with r3: st.caption(f"Phones: {case['related_phones'] or 'None returned'}")

    source_rows = [int(value) for value in str(case["supporting_row_numbers"]).split("; ") if value.isdigit()]
    case_hits = alerts[alerts["row_number"].isin(source_rows)].sort_values("transaction_date")
    case_tx = tx[tx["row_number"].isin(source_rows)].sort_values("transaction_date")
    st.markdown("#### Transaction timeline")
    timeline_cols = ["transaction_date", "transaction_id", "status", "amount", "currency", "card_display", "payer_country", "geoip_country"]
    st.dataframe(case_tx[[col for col in timeline_cols if col in case_tx]], use_container_width=True, hide_index=True)
    with st.expander("Rule evidence"):
        evidence_cols = ["rule_name", "severity", "reason", "observed_value", "baseline_value", "limit_value", "rule_scope", "evidence"]
        st.dataframe(case_hits[[col for col in evidence_cols if col in case_hits]], use_container_width=True, hide_index=True)
    st.markdown("#### Recommended action")
    st.success(str(case["recommended_action"]))
    with st.expander("Raw supporting transactions"):
        st.dataframe(case_tx, use_container_width=True, hide_index=True)


def _behaviour_snapshot(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    work = base[base["transaction_date"].notna()].copy()
    if work.empty:
        return pd.DataFrame(), pd.Series(dtype=float), pd.Series(dtype=float)
    status = work.get("status_l", work["status"].astype(str).str.lower())
    if "is_success" not in work:
        work["is_success"] = status.isin({"success", "approved", "captured", "settled"})
    if "is_decline" not in work:
        work["is_decline"] = status.isin({"fail", "failed", "declined", "rejected"})
    work["day"] = work["transaction_date"].dt.date
    daily = work.groupby("day").agg(
        transactions=("transaction_id", "count"),
        volume=("amount", "sum"),
        average_ticket=("amount", "mean"),
        approvals=("is_success", "sum"),
        declines=("is_decline", "sum"),
        countries=("payer_country", lambda values: values[values != ""].nunique()),
        cards=("card_hash", lambda values: values[values != ""].nunique()),
    ).reset_index().sort_values("day")
    daily["approval_rate"] = daily["approvals"] / daily["transactions"].replace(0, 1)
    daily["decline_rate"] = daily["declines"] / daily["transactions"].replace(0, 1)
    current = daily.iloc[-1]
    baseline = daily.iloc[:-1].tail(30).mean(numeric_only=True) if len(daily) > 1 else pd.Series(dtype=float)
    return daily, current, baseline


def _baseline_note(current: float, baseline: float, percentage=True) -> str:
    if pd.isna(baseline) or baseline == 0:
        return "No eligible prior baseline"
    change = (current / baseline) - 1
    return f"{change:+.1%} versus trailing baseline" if percentage else f"baseline {baseline:,.2f}"


def page_merchant_behaviour():
    st.title("Merchant Behaviour")
    tx, cases, alerts = st.session_state.tx, st.session_state.cases, st.session_state.alerts
    if tx is None or tx.empty:
        st.info("Load and evaluate transactions first.")
        return
    merchant = st.selectbox("Merchant", sorted(tx["merchant"].dropna().unique()))
    base = tx[tx["merchant"] == merchant]
    if "is_success" not in base:
        base = base.assign(
            is_success=base["status_l"].isin({"success", "approved", "captured", "settled"}),
            is_decline=base["status_l"].isin({"fail", "failed", "declined", "rejected"}),
            risk_score=0,
        )
    daily, current, baseline = _behaviour_snapshot(base)
    if daily.empty:
        st.warning("No dated activity is available for this merchant.")
        return
    st.caption(f"Current day {current['day']} compared with up to 30 prior observed days. Deterministic statistics, not machine learning.")
    m1, m2, m3, m4 = st.columns(4)
    with m1: kpi("Current volume", f"{current['volume']:,.2f}", _baseline_note(current["volume"], baseline.get("volume", float("nan"))))
    with m2: kpi("Transaction count", f"{int(current['transactions']):,}", _baseline_note(current["transactions"], baseline.get("transactions", float("nan"))))
    with m3: kpi("Average ticket", f"{current['average_ticket']:,.2f}", _baseline_note(current["average_ticket"], baseline.get("average_ticket", float("nan"))))
    with m4: kpi("Approval rate", f"{current['approval_rate']:.1%}", _baseline_note(current["approval_rate"], baseline.get("approval_rate", float("nan"))))
    st.markdown("#### Behaviour trend")
    st.line_chart(daily.set_index("day")[["volume", "transactions"]])
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Country distribution")
        st.dataframe(base.groupby("payer_country").agg(transactions=("transaction_id", "count"), amount=("amount", "sum")).reset_index().sort_values("transactions", ascending=False).head(10), use_container_width=True, hide_index=True)
    with c2:
        st.markdown("#### Card-brand distribution")
        st.dataframe(base.groupby("brand").agg(transactions=("transaction_id", "count"), amount=("amount", "sum")).reset_index().sort_values("transactions", ascending=False), use_container_width=True, hide_index=True)
    st.markdown("#### MID comparison")
    mid_compare = base.groupby("mid").agg(transactions=("transaction_id", "count"), volume=("amount", "sum"), approval_rate=("is_success", "mean"), decline_rate=("is_decline", "mean"), max_risk=("risk_score", "max")).reset_index().sort_values(["max_risk", "volume"], ascending=False)
    st.dataframe(mid_compare, use_container_width=True, hide_index=True)
    merchant_cases = cases[cases["merchant"] == merchant] if cases is not None and not cases.empty else pd.DataFrame()
    if not merchant_cases.empty:
        st.markdown("#### Top risks and linked entities")
        st.dataframe(merchant_cases[["alert_id", "severity", "risk_score", "investigative_insight", "primary_entity", "triggered_rules"]], use_container_width=True, hide_index=True)


def page_mid_behaviour():
    st.title("MID Behaviour")
    tx, cases = st.session_state.tx, st.session_state.cases
    if tx is None or tx.empty:
        st.info("Load and evaluate transactions first.")
        return
    mid = st.selectbox("MID", sorted(tx["mid"].dropna().unique()))
    base = tx[tx["mid"] == mid]
    sample = base.iloc[-1]
    limits = effective_limits(sample, st.session_state.rules)
    merchant = str(sample["merchant"])
    c1, c2, c3 = st.columns(3)
    with c1: kpi("Applied plan", limits.get("plan", "STANDARD"), f"merchant {merchant}")
    with c2: kpi("Inheritance source", limits.get("rule_scope", "global"), "most specific valid layer")
    with c3: kpi("MID alerts", f"{len(cases[cases['mid'] == mid]) if cases is not None and not cases.empty else 0:,}", "consolidated investigations")
    with st.expander("Effective thresholds and overrides"):
        safe_limits = {key: value for key, value in limits.items() if key not in {"success_statuses", "decline_statuses", "high_risk_countries"}}
        st.json(safe_limits)
        st.caption(f"Merchant override: {(st.session_state.rules.get('merchant_overrides') or {}).get(merchant, {})}")
        st.caption(f"MID override: {(st.session_state.rules.get('mid_overrides') or {}).get(mid, {})}")
    daily, current, baseline = _behaviour_snapshot(base)
    if not daily.empty:
        m1, m2, m3, m4 = st.columns(4)
        with m1: kpi("Current volume", f"{current['volume']:,.2f}", _baseline_note(current["volume"], baseline.get("volume", float("nan"))))
        with m2: kpi("Transactions", f"{int(current['transactions']):,}", _baseline_note(current["transactions"], baseline.get("transactions", float("nan"))))
        with m3: kpi("Approval rate", f"{current['approval_rate']:.1%}", _baseline_note(current["approval_rate"], baseline.get("approval_rate", float("nan"))))
        with m4: kpi("Decline rate", f"{current['decline_rate']:.1%}", _baseline_note(current["decline_rate"], baseline.get("decline_rate", float("nan"))))
        st.line_chart(daily.set_index("day")[["volume", "transactions", "approval_rate", "decline_rate"]])
    mid_cases = cases[cases["mid"] == mid] if cases is not None and not cases.empty else pd.DataFrame()
    if not mid_cases.empty:
        st.markdown("#### Top risks and rule hits")
        st.dataframe(mid_cases[["alert_id", "severity", "risk_score", "investigative_insight", "triggered_rules", "total_amount"]], use_container_width=True, hide_index=True)


def page_rule_performance():
    st.title("Rule Performance")
    tx, alerts, cases = st.session_state.tx, st.session_state.alerts, st.session_state.cases
    if tx is None:
        st.info("Run monitoring first.")
        return
    performance = rule_performance(alerts if alerts is not None else pd.DataFrame(), cases if cases is not None else pd.DataFrame(), len(tx), st.session_state.rules)
    preferred = ["name", "family", "classification", "severity", "alerts_generated", "transactions_matched", "alert_rate", "volume_status", "top_merchants", "top_mids", "testing_status", "last_threshold_change", "enabled"]
    st.dataframe(performance[[column for column in preferred if column in performance]], use_container_width=True, hide_index=True)
    excessive = performance[performance["volume_status"] == "Excessive"]
    if not excessive.empty:
        st.error(f"{len(excessive)} rule(s) matched at least 20% of evaluated transactions and require threshold or eligibility review.")
    if st.session_state.simulation is not None:
        st.markdown("#### Last simulation result")
        st.dataframe(st.session_state.simulation, use_container_width=True, hide_index=True)


def page_reports():
    st.title("Reports")
    tx, alerts, cases = st.session_state.tx, st.session_state.alerts, st.session_state.cases
    if tx is None:
        st.info("Load transactions and run monitoring first.")
        return
    if alerts is None:
        alerts = pd.DataFrame()
    if cases is None:
        cases = build_alert_cases(tx, alerts)
    report = cached_report(tx, alerts, cases, st.session_state.rules)
    st.download_button("Download Excel Monitoring Report", data=report, file_name="payouts_tm_monitoring_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.download_button("Download Investigation Alerts CSV", csv_download_bytes(cases), file_name="investigation_alerts.csv", mime="text/csv")
    st.download_button("Download Supporting Rule Hits CSV", csv_download_bytes(alerts), file_name="supporting_rule_hits.csv", mime="text/csv")
    st.download_button("Download Raw Transactions CSV", csv_download_bytes(tx), file_name="normalized_transactions.csv", mime="text/csv")
    st.download_button("Download Active Rules YAML", yaml.safe_dump(st.session_state.rules, sort_keys=False).encode(), file_name="active_rules.yaml")
    st.download_button("Download Active Rules JSON", json.dumps(st.session_state.rules, indent=2, default=str).encode(), file_name="active_rules.json")


def page_config():
    st.title("Configuration")
    st.caption("This is session-level for MVP. Later this can persist to SQLite/Postgres.")
    st.markdown("#### Full active configuration")
    txt = st.text_area("rules.yaml", yaml.safe_dump(st.session_state.rules, sort_keys=False), height=520)
    c1,c2 = st.columns(2)
    with c1:
        if st.button("Apply YAML config"):
            try:
                st.session_state.rules = yaml.safe_load(txt) or {}
                st.success("Configuration applied.")
            except Exception as e:
                st.error(f"Invalid YAML: {e}")
    with c2:
        if st.button("Reset to default"):
            st.session_state.rules = load_default_rules()
            st.success("Reset complete.")


def main():
    init_state()
    page = sidebar()
    if page == "Dashboard": page_dashboard()
    elif page == "Transaction Explorer": page_explorer()
    elif page == "Monitoring Run":
        st.title("Monitoring Run")
        tx = upload_and_map()
        run_monitoring(tx)
    elif page == "Rule Builder": page_rule_builder()
    elif page == "Rule Plans": page_rule_plans()
    elif page == "Behavior Search": page_behavior_search()
    elif page == "Alert Queue": page_alerts()
    elif page == "Merchant Behaviour": page_merchant_behaviour()
    elif page == "MID Behaviour": page_mid_behaviour()
    elif page == "Rule Performance": page_rule_performance()
    elif page == "Reports": page_reports()
    elif page == "Configuration": page_config()


if __name__ == "__main__":
    main()
