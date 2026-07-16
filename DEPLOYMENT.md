# Deployment Guide

## Target architecture

- Source control: public GitHub repository
- Default branch: `main`
- Streamlit entrypoint: `app.py`
- Runtime: Python 3.12
- Hosting: Streamlit Community Cloud
- Intended hosted data: synthetic or fully anonymized demonstrations only

## Pre-deployment controls

Before every release:

1. Confirm `git status` does not contain databases, exports, uploads, secrets, or private rules.
2. Confirm `rules.yaml` contains only synthetic entities and empty watchlists.
3. Run `python -m pytest -q` using Python 3.12.
4. Review dependency updates and the GitHub Actions result.
5. Test the bundled synthetic dataset locally.
6. Confirm public demo mode and SQLite-history restrictions remain enabled.

## GitHub configuration

Recommended repository settings:

- Keep the repository public only while it contains synthetic configuration and data.
- Enable private vulnerability reporting.
- Enable secret scanning and push protection.
- Protect `main` after the first release by requiring the CI check for pull requests.
- Keep Dependabot security updates enabled.

The repository `.gitignore` excludes local databases, credentials, uploads, exports, private configuration, generated PDFs, and the locally retained legacy duplicate directory.

## Streamlit Community Cloud

1. Sign in at <https://share.streamlit.io> and connect the GitHub account that owns the repository.
2. Select **Create app** and choose **Yup, I have an app**.
3. Configure:
   - Repository: `walawala254/payouts-transaction-monitoring-engine-mvp`
   - Branch: `main`
   - Main file path: `app.py`
4. Open **Advanced settings** and choose Python `3.12`.
5. Do not add production credentials or monitoring data.
6. Deploy and verify the health, bundled synthetic run, Alert Queue, and report download.

Suggested custom subdomain: `payouts-tm-engine-mvp` if available.

GitHub is the deployment source. A push to `main` causes Community Cloud to update the application; dependency changes can trigger a full rebuild.

## Environment settings

The public-safe defaults require no secrets. If environment values are supplied through a controlled deployment, use:

```text
PAYOUTS_TM_PUBLIC_DEMO=true
PAYOUTS_TM_MAX_UPLOAD_MB=25
PAYOUTS_TM_MAX_UPLOAD_ROWS=100000
PAYOUTS_TM_ENABLE_HISTORY=false
```

Do not commit `.streamlit/secrets.toml`. Configure genuine secrets only in Streamlit's app settings and access them through `st.secrets`.

## Verification after deployment

- The sidebar says **Public demo · synthetic data only**.
- The upload control is disabled until the synthetic/anonymized-data confirmation is selected.
- **Load bundled synthetic demo** works without an upload.
- SQLite history is disabled.
- Monitoring completes and creates investigation alerts.
- Excel and CSV reports download successfully.
- **Clear loaded data and cache** removes the active session data.
- No production entity names or watchlist entries are visible in Configuration or Rule Plans.

## Private or operational deployment

Do not turn the public demonstration into an operational monitoring service merely by changing an environment flag. A private/operational deployment also needs authentication and authorization, encrypted durable storage, secrets management, audit logging, retention controls, tenant isolation, production threshold governance, privacy review, monitoring, backups, and an incident-response process.
