# Security Policy

## Supported release

This repository is an early-stage public demonstration. Security fixes are applied to the latest `main` branch.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could expose transaction data, credentials, payment-card data, personal data, or monitoring thresholds.

Use GitHub's private vulnerability-reporting feature for this repository. Include the affected file or feature, reproduction steps, expected impact, and any suggested mitigation. Do not include live credentials or real customer records in the report.

## Data-handling boundary

The public deployment is intended for synthetic demonstration data only. Never commit or upload live transaction histories, production rules, watchlists, credentials, cardholder data, or personally identifiable information.

Local secrets belong in `.streamlit/secrets.toml` or environment variables. Both are excluded from Git. Streamlit Community Cloud secrets must be configured through the deployment settings.
