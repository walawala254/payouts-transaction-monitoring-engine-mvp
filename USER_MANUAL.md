# Payouts Transaction Monitoring Workbench

## User and Analyst Manual

Version: Current MVP as at 16 July 2026<br>
Audience: Transaction-monitoring analysts, risk operations, rule administrators and reviewers

> This workbench is an analyst-support tool. A rule match is an indicator requiring review, not proof of fraud, money laundering or policy breach. The application does not claim Visa certification or formal regulatory compliance.

## 1. What the tool does

The Payouts Transaction Monitoring Workbench evaluates an uploaded CSV or Excel transaction file against configurable transaction-monitoring rules. It then:

1. maps and normalises the transaction fields;
2. resolves the applicable plan, merchant, MID and temporary settings;
3. runs enabled monitoring rules;
4. scores flagged transactions;
5. combines related rule hits into investigation alerts;
6. provides merchant, MID and rule-performance views; and
7. exports the results, evidence and normalised source rows.

The operating flow is:

`Upload -> map and normalise -> run monitoring -> review summary -> investigate alerts -> export`

The tool is currently file-based and batch-oriented. It is not a real-time payment decision engine, case-management system, CRM or sanctions-screening platform.

## 2. Important terms

| Term | Meaning in this tool |
|---|---|
| Transaction | One normalised source row. A generated `row_number` keeps duplicate transaction IDs separate. |
| Flagged transaction | A transaction with at least one executable monitoring-rule hit and a transaction `risk_score` above zero. |
| Rule hit | One instance of one monitoring rule producing evidence. A transaction can have several hits. |
| Investigation alert | A consolidated case shown in the Alert Queue. Related hits are grouped by merchant, MID, aggregation entity and day. |
| Primary entity | The aggregation value around which the alert was formed, such as a card token, email, phone, MID or merchant/MID pair. |
| Preventive-control breach | A configured acceptance-limit breach retained as context on the transaction. It does not create a TM alert. |
| Baseline | A deterministic trailing average calculated from eligible prior days in the uploaded data. It is not machine learning. |
| Rule scope | The most specific configuration layer that supplied the effective settings. |
| Alert rate | Flagged transactions divided by transactions evaluated. It is not the number of investigation alerts divided by transactions. |

## 3. Before starting a monitoring run

### 3.1 Prepare the source file

The upload must be CSV, XLS or XLSX. Use one row per transaction and retain enough history for the behaviour being tested.

For reliable results:

- use stable merchant and MID identifiers;
- use parseable transaction timestamps, including time where velocity rules are required;
- use consistent transaction statuses;
- use numeric transaction and merchant amounts;
- represent card numbers consistently across the entire file;
- use consistent country codes or country names in both country fields;
- identify refunds and reversals clearly in the transaction `type`; and
- avoid mixing currencies in amount aggregations unless the figures are already normalised to a common currency.

The recognised success statuses are `success`, `approved`, `captured` and `settled`. The recognised decline statuses are `fail`, `failed`, `declined` and `rejected`. Matching is case-insensitive after normalisation. Other values remain in the data but do not count as approvals or declines.

### 3.2 Fields understood by the tool

| Canonical field | Used for |
|---|---|
| `transaction_id` | Evidence linkage and exports; generated from row order if entirely absent |
| `merchant` | Merchant aggregation, reporting, plans and overrides |
| `mid` | MID aggregation, reporting, plans, overrides and dormancy |
| `transaction_date` | Velocity, daily aggregation, baselines and dormancy |
| `type` | Refund and reversal identification |
| `status` | Approval and decline behaviour |
| `amount` | Transaction value, velocity context, volume and reports |
| `merchant_amount` | Preventive merchant-value context; defaults to `amount` if absent |
| `currency` | Evidence and reporting context; no exchange-rate conversion is performed |
| `brand` | Visa/Mastercard-specific limits and reporting |
| `card_number` | Card hashing, masking, velocity, linkage and watchlists |
| `payer_name` | Raw investigation context |
| `payer_country` | Geographic rules and reporting |
| `payer_email` | Identity linkage and watchlists |
| `payer_phone` | Identity linkage and watchlists |
| `geoip_country` | Country mismatch and high-risk-country rules |
| `gateway_id` | Raw investigation context |
| `card_type`, `card_category` | Raw context and automatic plan hints |
| `issuer`, `issuer_country` | Issuer and country reporting |
| `decline_reason`, `decline_type` | Decline analysis and evidence |

Device fingerprint, source IP, stable customer ID, MCC, chargeback, MID lifecycle and original-refund linkage are not currently available as executable fields.

### 3.3 Data-handling caution

Uploaded data may contain personal and payment information. Use access controls appropriate to your organisation, do not publish real transaction files to a public GitHub repository, and restrict exported reports to authorised users. The app displays a masked card value and a derived token in alert evidence, but the normalised raw transaction export still contains the uploaded `card_number` representation.

## 4. Quick-start procedure

1. Open **Monitoring Run** from the sidebar.
2. Upload the transaction file.
3. Confirm the reported row and column counts.
4. Open **Column mapping** and verify every field used by the required rules.
5. Select **Normalize / Refresh Data** after changing any mapping.
6. Review the sidebar rule-family toggles.
7. Leave **Simulator mode** off for a normal run.
8. Select **Run Monitoring Engine**.
9. Review the run totals and any data-quality warnings.
10. Open **Dashboard** to identify the largest risk concentrations.
11. Open **Alert Queue** and investigate Critical and High alerts first.
12. Use **Merchant Behaviour**, **MID Behaviour** and **Behavior Search** to corroborate the alert.
13. Check **Rule Performance** for excessive alert volumes.
14. Download the required outputs from **Reports**.

If a rule threshold or plan has been changed, run a simulation before accepting the change.

## 5. How the engine works

### 5.1 Normalisation

The application infers common Payouts/Akurateco-style column names. It then converts dates and amounts, trims text, normalises status and brand values, normalises email and phone keys, and derives:

- transaction day, week, month and hour;
- a SHA-256-derived 16-character card token;
- a masked card display using the last four characters;
- sequential source `row_number`; and
- success and decline indicators.

Always correct the column mapping before relying on the output. A successfully uploaded file can still produce unusable monitoring if critical fields were mapped incorrectly.

### 5.2 Rule inheritance

Effective settings are resolved in this order:

1. global defaults;
2. antifraud plan;
3. merchant detailed rules and merchant override;
4. MID detailed rules and MID override; and
5. a valid temporary override.

The most specific valid setting wins. The `rule_scope` in rule-hit evidence shows the effective source, such as `plan:STANDARD`, `merchant:<name>`, `mid:<id>` or `temporary:<override-id>`.

A plan can be assigned explicitly through the MID plan map or merchant plan map. If neither exists, the app looks for terms such as forex, gaming, bet or casino in limited transaction descriptors; otherwise it uses `STANDARD`. Explicit mappings are safer than inferred plans.

### 5.3 Preventive controls versus monitoring rules

Four configured processing controls do not execute as TM alerts:

- transaction below the configured minimum;
- transaction above the configured maximum;
- merchant amount below the configured minimum; and
- merchant amount above the configured maximum.

Any breach is written to `preventive_control_breaches` on the normalised transaction. It is investigation context only. It must not be interpreted as a suspicious-activity alert or evidence that the transaction was actually blocked.

### 5.4 Raw hits, transaction scoring and cases

Each monitoring hit returns the rule, family, severity, weight, reason, advice, effective scope, aggregation key, limit, observed value, baseline where applicable and supporting evidence.

At transaction level, all hit weights on that source row are added:

| Transaction score | Risk level |
|---:|---|
| 0 | None |
| 1-24 | Low |
| 25-59 | Medium |
| 60-99 | High |
| 100 or more | Critical |

At investigation-alert level:

- related hits are grouped by merchant, MID, aggregation key and calendar day;
- duplicate hits from the same rule contribute that rule's weight only once;
- the case score is capped at 100; and
- case severity is the highest configured severity among its supporting hits.

Consequently, case severity and case risk score are not interchangeable. Review both, then read the actual drivers and evidence.

## 6. Current monitoring rule library

### 6.1 Velocity and decline behaviour

| Rule | What causes a hit | How to interpret it |
|---|---|---|
| `CARD_APPROVED_VELOCITY` | Approved count for the same card within MID and brand exceeds its effective limit and time window. | May indicate compromised-card use, cycling or unusually concentrated legitimate activity. Check customer, amount, timing and merchant context. |
| `CARD_DECLINE_VELOCITY` | Decline count for the same card within MID and brand exceeds its effective limit and time window. | Possible card testing or repeated authorisation probing. Separate gateway retries and issuer/service failures from customer-driven attempts. |
| `DECLINE_THEN_APPROVAL` | An approval follows at least the configured number of declines for the same card in the decline window. | Stronger card-testing narrative than declines alone. Verify sequence, issuer responses, identity changes and the successful transaction. |
| `MERCHANT_APPROVAL_RATE_DROP` | Current merchant/MID approval rate falls below its eligible trailing baseline by the configured percentage-point amount. | May reflect attack traffic, routing failure, issuer problems or poor traffic quality. Review decline reasons before assigning suspicion. |

### 6.2 Merchant and MID behaviour

| Rule | What causes a hit | How to interpret it |
|---|---|---|
| `MERCHANT_DAILY_VOLUME` | Approved amount for merchant, MID, brand and day exceeds the effective daily limit. | Critical operating-threshold signal. Confirm planned campaigns, growth, settlement timing and the applied scope. One representative hit is produced per breached group/day. |
| `MERCHANT_VOLUME_BASELINE_SPIKE` | Current approved daily volume exceeds the eligible trailing average by the configured multiplier. | A meaningful behavioural change, but seasonality, promotions and onboarding growth can explain it. Compare customers, countries, cards and other MIDs. |
| `DORMANT_MID_RESUMPTION` | A MID transaction follows an observed inactivity gap at least as long as the configured dormancy period. | Confirm whether the MID was expected to be active and review the first resumed activity. The tool observes gaps in the upload; it does not know official MID status. |

### 6.3 Customer identity and cross-merchant linkage

| Rule | What causes a hit | How to interpret it |
|---|---|---|
| `EMAIL_USED_WITH_MULTIPLE_CARDS` | One normalised email is linked to more than the configured card limit within a merchant in the uploaded period. | Possible synthetic identity, takeover or shared credentials. Consider family, corporate and booking-desk use. |
| `PHONE_USED_WITH_MULTIPLE_CARDS` | One normalised phone is linked to more than the configured card limit within a merchant in the uploaded period. | Similar to email linkage; also consider recycled phone numbers and shared contact centres. |
| `CARD_USED_ACROSS_MERCHANTS` | One card token appears across at least the configured number of merchants in the evaluated file. | Possible compromise, collusive processing or transaction-laundering linkage. First exclude related merchants, wallets and common travel use. |

### 6.4 Geography

| Rule | What causes a hit | How to interpret it |
|---|---|---|
| `PAYER_COUNTRY_GEOIP_MISMATCH` | Non-empty payer and GeoIP countries differ after upper-casing. | Contextual location inconsistency. Travel, roaming, VPNs, proxies and inconsistent country formats are common explanations. |
| `HIGH_RISK_COUNTRY` | Payer or GeoIP country exactly matches an entry in the configured high-risk list. | Risk-based review trigger, not a prohibited-country conclusion. Validate list governance and country formatting. The default list is empty. |

### 6.5 Patterns, refunds and reversals

| Rule | What causes a hit | How to interpret it |
|---|---|---|
| `REPEATED_CARD_AMOUNT` | The same card and exact amount appear more than once within the configured short window for one merchant. | Weak structuring/retry proxy. Check idempotency, status, retry behaviour and whether the repetitions are commercially normal. |
| `MERCHANT_REFUND_RATE_SPIKE` | Current refund/reversal rate exceeds its eligible trailing baseline by the configured multiplier, subject to daily-count eligibility. | Possible refund abuse, suspicious fund movement or fulfilment problems. Original purchase/refund linkage is not available, so corroboration is essential. |

### 6.6 Internal watchlists

| Rule | Match method | Interpretation requirement |
|---|---|---|
| `WATCHLIST_EMAIL` | Exact normalised email | Validate list source, reason, age and match accuracy. |
| `WATCHLIST_PHONE` | Exact phone after retaining digits and `+` | Confirm country-code conventions and list governance. |
| `WATCHLIST_CARD` | Exact uploaded card representation | Confirm consistent PAN/token representation. Alert evidence is masked, but raw normalised data retains the source value. |
| `WATCHLIST_BIN` | First six characters match configured BIN | A broad indicator affecting many unrelated cards; always require supporting context. |

Empty watchlists produce no watchlist hits.

## 7. Baseline rules

Baseline rules use prior observed calendar days for the same merchant and MID. The defaults are a 30-day lookback and at least seven prior eligible days. The current day is excluded from its own baseline.

Baseline results are reliable only when:

- the uploaded file includes sufficient earlier history;
- dates are correctly mapped and parsed;
- merchant and MID identifiers remain stable;
- status and transaction type are normalised consistently; and
- amounts being compared are economically comparable.

The approval-rate and refund-rate rules also require the configured minimum daily transaction count, which defaults to 10.

No eligible baseline means no baseline-rule hit. It does not mean the current behaviour is normal. Saved SQLite history is not currently loaded into later runs, so include the required lookback history in each evaluation file.

## 8. Using each screen

### Dashboard — Monitoring Run Summary

Use this page to understand the run before opening individual alerts.

- **Transactions processed** is the number of normalised rows.
- **Transactions flagged** counts rows with a positive monitoring score.
- **Alert rate** is flagged rows divided by processed rows.
- **Unique alerts** counts consolidated investigation cases.
- **Rule hits** counts all supporting scenario matches; this will often exceed unique alerts.
- **High/Critical alerts** is the priority case count.
- **Top triggered rules** identifies the largest workload drivers, not necessarily the greatest risk.
- **Top affected merchants/MIDs** identifies concentration by case count, maximum case score and amount.
- **Data-quality warnings** show missing-field rates and affected monitoring areas.

High volume concentrated in one merchant can mean genuine concentration, a merchant-specific event, poor data or a threshold needing calibration.

### Transaction Explorer

Use the explorer to verify source data and search by merchant, MID, status, card brand, amount or free text. After a monitoring run, **Flagged only** limits the table to transactions with positive risk scores.

This is a row-level view. It does not replace the Alert Queue because it does not tell the complete case story.

### Monitoring Run

This page controls upload, mapping and evaluation.

- **Save to SQLite history** appends transactions, raw rule hits and investigation alerts to the local database for audit/reference. It does not make that history part of future baseline evaluation.
- **Simulator mode** compares the accepted session settings with the proposed working settings on the same upload.
- **Top monitoring scenarios** shows raw hit counts by rule and severity.
- **Raw rule-hit evidence** exposes the detailed evidence behind the summary.

Sidebar toggles disable their corresponding rule groups for the working session. Baseline rules have their own toggle. A disabled rule does not create new hits.

### Alert Queue and Alert Detail

Prioritise Critical and High cases, then consider score, value, recency and concentration.

For each case, answer these questions in order:

1. **What happened?** Read the investigative insight and activity period.
2. **How serious is it?** Review severity, score, transaction count, amount and declines.
3. **Why was it flagged?** Read every top risk driver; do not rely on the title alone.
4. **What is normal?** Review the baseline comparison, if one is available.
5. **What is connected?** Review related cards, emails and phones.
6. **What was the sequence?** Inspect the transaction timeline, especially decline-to-approval order.
7. **What exact rule evidence exists?** Expand Rule evidence and compare observed, limit and baseline values.
8. **What should happen next?** Follow the recommended action, adapted to internal policy.
9. **Can the conclusion be reproduced?** Expand the raw supporting transactions and retain the alert ID in working papers.

The on-screen alert `status` is currently initialised as `New`; it is not a persistent case workflow or disposition record.

The timeline and raw supporting table contain the rows that directly generated rule hits. For representative aggregate hits, such as a daily-volume breach, they may not contain every transaction used to calculate the aggregate. Use the observed value as the alert measure, then expand the entity and time period in Transaction Explorer or the normalised export.

### Merchant Behaviour

This page compares the latest observed merchant day with up to 30 prior observed days and shows:

- current volume and transaction count;
- average ticket and approval rate;
- daily volume/count trend;
- payer-country and card-brand distributions;
- comparison across the merchant's MIDs; and
- linked investigation alerts.

A percentage change is descriptive context. It is not automatically suspicious. Check whether the baseline contains enough representative business days and whether the latest day is complete.

### MID Behaviour

Use this page to confirm:

- applied antifraud plan;
- effective inheritance source;
- effective thresholds;
- merchant and MID overrides;
- latest behaviour versus prior days; and
- the MID's linked cases.

The displayed effective settings are based on a sample transaction for that MID. If settings can vary by brand or temporary effective dates, inspect the rule-hit `rule_scope` and limit evidence for the exact transaction.

### Rule Performance

This page shows rule hits, matched transactions, alert rate, top affected merchants/MIDs and governance metadata.

Volume labels mean:

| Label | Matched-transaction rate | Meaning |
|---|---:|---|
| Normal | Below 5% | No automatic volume warning; quality still requires review |
| Review | 5% to below 20% | Check threshold, eligibility and merchant concentration |
| Excessive | 20% or more | Do not activate or retain without investigation and calibration |

These labels measure workload concentration. They do not estimate the true false-positive rate because analyst dispositions are not yet stored.

### Rule Builder

Use Rule Builder to search and inspect the governed rule catalogue. Editable catalogue fields include name, family, classification, applicable entity, severity, risk weight and enabled status. Global parameters control common thresholds and country lists.

Changes apply to the current Streamlit session. Use simulation before accepting a material change, then download the active YAML for controlled review and deployment.

The **Preventive-control catalogue** explains controls excluded from TM execution. **Future-data requirements** lists monitoring that cannot be implemented reliably with the current transaction fields.

### Rule Plans & Overrides

Use this page to maintain:

- plan-level parameters;
- MID and merchant brand-specific rule matrices;
- merchant-to-plan and MID-to-plan maps;
- merchant and MID patch overrides;
- governed, expiring temporary overrides; and
- baseline lookback and minimum-history settings.

For a temporary override, record an ID, scope, start, expiry, reason and approver. Do not use permanent temporary overrides to bypass normal governance.

### Behavior Search

Behavior Search is an investigative utility, not an alert generator. It can find:

- cards used by many emails;
- emails used with many cards;
- phones used with many cards;
- cards appearing across merchants; and
- repeated exact card/amount combinations.

Results cover the loaded file and the analyst-selected minimum count. Use them to find related activity and corroborate an existing alert.

### Reports

Use this page after the monitoring run. Available downloads are:

- Excel Monitoring Report;
- Investigation Alerts CSV;
- Supporting Rule Hits CSV;
- Raw/normalised Transactions CSV;
- Active Rules YAML; and
- Active Rules JSON.

### Configuration

This page exposes the full active YAML configuration. Invalid YAML is rejected, but semantic mistakes can still create poor monitoring results. Use controlled review, simulation and versioning before replacing the default `rules.yaml`.

## 9. Interpreting the Excel report

| Sheet | What it answers | Interpretation notes |
|---|---|---|
| Executive Story | What is the size, status mix and alert load of the run? | Start here. Distinguish flagged transactions, raw hits and cases. |
| Portfolio Trend | How do volume, approvals, declines and alerts change by day/week/month? | Look for changes that align with alert peaks; check partial periods. |
| Status Funnel | How are transaction types distributed across statuses? | Unexpected status labels may reveal mapping/normalisation issues. |
| Merchant Risk Ranking | Which merchant/MID combinations concentrate alerts, value and cards? | High amount alone is not high risk; combine alert rate and scenario quality. |
| MID Brand Risk | Are risks concentrated by MID and card brand? | Compare to brand-specific configured thresholds. |
| Country Corridor Risk | Which payer/issuer-country pairs carry activity and alerts? | Country formatting and missing values materially affect this table. |
| Issuer Risk Ranking | Which issuers or issuer countries concentrate risk? | Use as supporting context, not issuer guilt attribution. |
| Card Concentration | Which card tokens recur across transactions, merchants or countries? | Validate whether the source card representation is stable and unique. |
| AML Scenario Heatmap | Which rules drive hits, impacted entities and amount? | This is a scenario workload view, not a confirmed-AML count. |
| AML TM Coverage | Which broad monitoring areas produced hits? | A zero may mean no activity, disabled rules, missing data or empty watchlists. |
| Decline Reasons | Where are declines concentrated and why? | Use to separate attack patterns from routing, issuer or technical issues. |
| Approval Ratios | Which merchant/MIDs show the lowest approval ratios? | Give greater weight to entities with meaningful transaction counts. |
| Data Quality | Which critical fields are missing and which rules are affected? | Resolve Critical and Warning fields before relying on affected coverage. |
| Rule Performance | Which rules generate workload and concentration? | Review rules at 5% match rate and treat 20% or above as excessive. |
| Top Successful Trx | What are the highest-value successful transactions? | Context only unless supported by monitoring indicators. Limited to top 1,000. |
| Top Declined Trx | What are the highest-value declined transactions? | Look for repeated cards, reasons and later approvals. Limited to top 1,000. |
| Investigation Alerts | What cases should analysts review? | Primary working queue for exported investigation. |
| Flagged Transactions | Which transaction rows have a positive score? | One row can support several rule hits and one or more analytical narratives. |
| Rule Hits | What exact evidence caused each match? | Best sheet for rule validation and audit trail. |
| Normalized Transactions | What data was actually evaluated? | Use to verify mapping and reproduce results. |

The report generator limits most analytical tables to 50,000 rows and the two top-transaction sheets to 1,000 rows. The full normalised transactions, raw rule hits and investigation alerts remain separate report sheets and CSV downloads, subject to normal spreadsheet capacity.

## 10. Safe rule-change and simulation procedure

1. Load a historical file representative of ordinary, peak and suspicious activity.
2. Record the current rule settings and run totals.
3. Change only the intended threshold, plan, severity or enablement setting.
4. Turn on **Simulator mode**.
5. Run the engine.
6. Compare current and proposed transactions matched, cases, rule hits and severity mix.
7. Review the top affected merchants and MIDs.
8. Investigate the proposed sample matches, including legitimate concentrations.
9. Treat 5% or more as a review warning and 20% or more as excessive volume.
10. Obtain the required approval and export the proposed active rules.

`estimated_false_positive_concentration` is the share of proposed raw hits belonging to the single most-affected merchant. It is a concentration proxy, not a measured false-positive percentage.

## 11. Recommended analyst disposition process

Because the MVP does not persist case decisions, maintain a controlled external investigation log containing at least:

- alert ID;
- run date and source-file reference;
- analyst and reviewer;
- merchant and MID;
- alert severity and score;
- triggered rules;
- evidence reviewed;
- outcome, such as escalated, genuine activity, false positive or data issue;
- rationale;
- action taken; and
- closure and review timestamps.

Before closing an alert as a false positive, state the specific legitimate explanation and the evidence supporting it. Repeated legitimate explanations should feed rule or entity-level threshold calibration, not repeated ad hoc dismissal.

## 12. Common false-positive patterns

| Pattern | Checks to perform |
|---|---|
| Planned sales campaign or seasonal peak | Compare dates, merchant notice, volume mix, customer diversity and prior equivalent periods. |
| Family/corporate card or shared booking contact | Compare payer names, merchant purpose, card ownership and consistent contact details. |
| Gateway retry or duplicate submission | Compare transaction IDs, timestamps, statuses, decline reasons, gateway ID and exact amounts. |
| Travel, VPN, roaming or corporate network | Compare payer/issuer countries, prior behaviour, timing and other takeover indicators. |
| Related merchants under one group | Confirm ownership and legitimate cross-merchant card behaviour before dismissing linkage. |
| New or rapidly growing MID | Confirm onboarding/growth approval and compare transaction quality, countries and customer reuse. |
| Broad BIN watchlist match | Validate the reason for listing the BIN and require corroborating transaction evidence. |
| Partial current day | Avoid treating an incomplete day's count/rate as directly comparable to complete historical days. |

## 13. Data-quality interpretation

For each critical field, the app reports a missing-row count and rate:

- **Usable:** below 10% missing;
- **Warning:** 10% to below 50% missing; and
- **Critical:** 50% or more missing.

These bands are operational indicators, not guarantees. Even a low missing rate can invalidate a specific alert if the relevant row or entity is affected. A field can also be populated but wrong—for example, a date mapped from the wrong source column—so perform reasonableness checks in the Transaction Explorer.

## 14. Current limitations

- Monitoring runs use the currently uploaded file; SQLite history is append-only and is not read back into new evaluations.
- Cross-merchant, email and phone linkage use the evaluated upload period rather than a persistent customer history.
- Baselines cover daily count, approved volume, approval rate and refund rate only. Hour-of-day, day-of-week, country and card-brand distribution baselines are not executable yet.
- There is no stable customer ID, device fingerprint or source IP monitoring.
- GeoIP country is not equivalent to IP intelligence.
- There is no chargeback correlation, MCC intelligence, official MID lifecycle data or original refund-transaction linkage.
- Amount aggregation does not convert currencies. Mixed-currency volume results can be misleading.
- Card identity is derived from the uploaded representation. Masked or inconsistent PAN values can cause false linkage or missed linkage.
- Country comparison is string-based after upper-casing; `KE` and `Kenya` do not normalise to the same value.
- Repeated exact amount is only a weak structuring proxy.
- Watchlists are internal exact-match lists and have no external intelligence integration.
- Some rules that do not set an entity-specific aggregation key fall back to MID-level case grouping. Confirm in Rule Hits that one consolidated case has not combined unrelated entities within the same MID and day.
- Representative aggregate hits retain the row that carries the alert, not every row contributing to the aggregate calculation.
- Alert statuses and analyst dispositions are not persisted as a case workflow.
- Rule changes are session-level until the exported configuration is reviewed and installed as `rules.yaml`.
- The application has no multi-user access control or audit-grade configuration approval workflow.
- The approximate 100,000-row target has been tested synthetically, but performance depends on rule-hit volume, machine resources and report size.
- This is not real-time decisioning and does not block or decline transactions.

## 15. Troubleshooting

### The file uploads but no alerts appear

Check column mapping, date parsing, status spelling, sidebar toggles, rule enablement, thresholds, empty watchlists and whether sufficient history exists for baseline rules.

### A baseline rule does not trigger

Confirm that the same merchant/MID has the required number of prior observed days, the current date is later than those days, and the current metric exceeds the configured deviation threshold. A first day or short file has no eligible baseline.

### Alert volumes are unexpectedly high

Review Rule Performance, merchant concentration, duplicate/retry behaviour, status mapping, card representation and the effective `rule_scope`. Simulate a change rather than immediately disabling the rule.

### Results changed after editing a rule

Rule and toggle changes are session-level and cached by their inputs. Re-run the Monitoring Engine after the change. Use Simulator mode to compare the accepted and proposed configurations.

### The wrong plan or threshold was applied

Check MID plan mapping first, then merchant plan mapping, detailed merchant/MID matrices, patch overrides and active temporary overrides. Inspect the exact rule hit's `rule_scope` and `limit_value`.

### Countries mismatch unexpectedly

Standardise both fields to the same coding convention before upload. The tool upper-cases strings but does not translate codes to names.

## 16. Minimum review checklist

Before issuing or relying on a report, confirm:

- [ ] the source file and reporting period are correct;
- [ ] column mappings are verified;
- [ ] critical data-quality warnings are understood;
- [ ] currencies and amounts are comparable;
- [ ] rule toggles and active rules are appropriate;
- [ ] the intended plan and overrides were applied;
- [ ] the file contains sufficient baseline history;
- [ ] Critical and High alerts were investigated;
- [ ] top rule and merchant concentrations were reviewed for calibration issues;
- [ ] evidence and raw supporting rows were retained;
- [ ] conclusions distinguish indicators from confirmed outcomes; and
- [ ] exports are stored and shared securely.

## 17. Related project documentation

- `README.md` — installation, scope and basic workflow
- `TM_AUDIT_AND_REFACTOR.md` — rule audit, coverage, gap analysis, tests and remaining implementation backlog
- `rules.yaml` — active rule catalogue, thresholds, plans, matrices, watchlists and overrides
