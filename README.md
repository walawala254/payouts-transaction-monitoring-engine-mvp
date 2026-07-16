# Payouts Transaction Monitoring Engine MVP

[![CI](https://github.com/walawala254/payouts-transaction-monitoring-engine-mvp/actions/workflows/ci.yml/badge.svg)](https://github.com/walawala254/payouts-transaction-monitoring-engine-mvp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/built%20with-Streamlit-ff4b4b.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A file-based Streamlit transaction-monitoring workbench for PSP and acquiring demonstrations. It normalizes uploaded transactions, evaluates governed monitoring rules, consolidates related hits into investigation alerts, compares merchant/MID behaviour with deterministic baselines, and exports the evidence.

> **Public demo boundary:** use synthetic or fully anonymized data only. Do not upload or commit live cardholder data, personal data, production transaction history, operational watchlists, credentials, or confidential monitoring thresholds.

This project is an early-stage analyst-support MVP. A rule match is an indicator for review, not proof of fraud, money laundering, or a policy breach. The project does not claim Visa certification or formal regulatory compliance.

## Capabilities

- CSV, XLS, and XLSX uploads with automatic column inference and manual mapping
- Pre-run mapping, row-limit, date, amount, and critical-field validation
- Governed monitoring-rule catalogue and separate preventive-control context
- Global, plan, merchant, MID, and expiring temporary inheritance layers
- Card velocity, decline, identity-linkage, geography, watchlist, cross-merchant, baseline, refund, dormancy, and repeated-pattern monitoring
- Transaction scoring and consolidated investigation alerts
- Merchant, MID, rule-performance, behaviour-search, and alert-detail views
- Current-versus-proposed rule simulation
- Data-quality dependency reporting
- Excel, CSV, YAML, and JSON exports with formula-injection protection
- Bounded Streamlit caching and an explicit session-data clear control
- Bundled synthetic demonstration data

## Safe quick start

Use Python 3.12, matching the CI and Streamlit Community Cloud deployment environment.

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
streamlit run app.py
```

In the app, select **Load bundled synthetic demo**, run the monitoring engine, and review the Alert Queue.

## Configuration modes

Public demo mode is the safe default:

```text
PAYOUTS_TM_PUBLIC_DEMO=true
PAYOUTS_TM_MAX_UPLOAD_MB=25
PAYOUTS_TM_MAX_UPLOAD_ROWS=100000
PAYOUTS_TM_ENABLE_HISTORY=false
```

SQLite history can only be enabled when public demo mode is disabled. It is intended for controlled local/private use and is not a durable Community Cloud datastore.

The committed `rules.yaml` contains synthetic `DEMO_*` entities and example thresholds. Calibrate and approve a private configuration before operational use. Never commit production mappings, watchlists, overrides, or thresholds to a public repository.

## Tests

```bash
python -m pytest -q
```

The synthetic 100,000-row performance check is separate from CI:

```bash
python tests/benchmark_100k.py
```

## Repository structure

```text
app.py                         Streamlit interface
transaction_monitor.py         Normalization, rules, cases, simulation, and exports
rules.yaml                      Synthetic public-demo rule configuration
sample_data/                    Synthetic demonstration transactions
tests/                          Regression tests and manual benchmark
.streamlit/config.toml          Streamlit theme and upload limit
.github/workflows/ci.yml        Python 3.12 Linux CI
USER_MANUAL.md                  User and analyst instructions
TM_AUDIT_AND_REFACTOR.md        Rule and reporting audit record
DEPLOYMENT.md                   GitHub and Streamlit deployment guide
SECURITY.md                     Security and data-handling policy
```

## Documentation

- [User and Analyst Manual](USER_MANUAL.md)
- [Audit and Refactor Report](TM_AUDIT_AND_REFACTOR.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Security Policy](SECURITY.md)

## Known limitations

- Batch/file processing rather than real-time decisioning
- No persisted analyst case workflow or multi-user authorization
- Uploaded history is the basis for linkage and baselines; SQLite history is not read into later evaluations
- No stable customer ID, source IP, device fingerprint, chargeback linkage, MID lifecycle feed, or original-refund linkage
- No currency conversion for cross-currency amount aggregation
- Public Community Cloud deployment is for synthetic demonstration data only

See the manual and audit report for detailed interpretation guidance and the prioritized product backlog.

## License

Released under the [MIT License](LICENSE).
