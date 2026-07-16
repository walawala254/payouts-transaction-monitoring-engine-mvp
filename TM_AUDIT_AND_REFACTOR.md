# Transaction Monitoring Audit and Refactor

Date: 2026-07-15<br>
Benchmark: "Visa-grade" is used only as a quality benchmark. This application does not claim Visa certification or formal compliance.

## Executive result

The original application was a useful file-based rule-hit workbench. It had 16 executable codes, configurable plans and merchant/MID thresholds, basic scoring, raw alert review and Excel export. It did not have governed rule definitions, case-level alerts, behavioral baselines, comparative simulation, rule-performance reporting or automated tests.

The refactor preserves the workflow and architecture:

`Upload -> validate/normalize -> evaluate monitoring rules -> score/consolidate alerts -> investigate -> export`

Four processing-limit checks were removed from TM execution and retained as preventive-control context. Eighteen monitoring scenarios now use a governed catalogue. Related hits are consolidated into investigation alerts while all hit and transaction evidence remains available.

## Original rule inventory and classification

| Original rule | Classification | Decision |
|---|---|---|
| CARD_APPROVED_VELOCITY | Monitoring Rule | Retained and governed |
| CARD_DECLINE_VELOCITY | Monitoring Rule | Retained and governed |
| MERCHANT_DAILY_VOLUME | Monitoring Rule | Retained; clarified as merchant/MID/brand aggregation |
| HIGH_AMOUNT_ABOVE_PLAN_LIMIT | Preventive Control | Removed from TM execution; retained as transaction context |
| LOW_AMOUNT_BELOW_MINIMUM | Preventive Control | Removed from TM execution; retained as transaction context |
| MERCHANT_VALUE_ABOVE_LIMIT | Preventive Control | Removed from TM execution; retained as transaction context |
| MERCHANT_VALUE_BELOW_MINIMUM | Preventive Control | Removed from TM execution; retained as transaction context |
| PAYER_COUNTRY_GEOIP_MISMATCH | Monitoring Rule | Retained and governed |
| HIGH_RISK_COUNTRY | Monitoring Rule | Retained and governed |
| EMAIL_USED_WITH_MULTIPLE_CARDS | Monitoring Rule | Retained with normalized email aggregation |
| PHONE_USED_WITH_MULTIPLE_CARDS | Monitoring Rule | Retained with normalized phone aggregation |
| REPEATED_CARD_AMOUNT | Monitoring Rule | Retained; false-positive controls documented |
| WATCHLIST_EMAIL | Monitoring Rule | Retained and governed |
| WATCHLIST_PHONE | Monitoring Rule | Retained with normalized phone matching |
| WATCHLIST_CARD | Monitoring Rule | Retained with masked alert evidence |
| WATCHLIST_BIN | Monitoring Rule | Retained; BIN false-positive risk documented |

The original Behavior Search functions were classified as investigative utilities. They enrich review but do not independently create alerts.

## New monitoring rules

| Rule | Family | Purpose |
|---|---|---|
| CARD_USED_ACROSS_MERCHANTS | Cross-merchant linkage | Detect a card token used across an abnormal number of merchants |
| DECLINE_THEN_APPROVAL | Decline behaviour | Detect approval after concentrated failed attempts |
| MERCHANT_VOLUME_BASELINE_SPIKE | Merchant behaviour | Detect approved volume materially above a trailing average |
| MERCHANT_APPROVAL_RATE_DROP | Decline behaviour | Detect approval-rate deterioration against recent behavior |
| MERCHANT_REFUND_RATE_SPIKE | Refund and reversal abuse | Detect refund/reversal-rate deviation where transaction type is usable |
| DORMANT_MID_RESUMPTION | Dormancy and sudden spikes | Detect resumed activity after an observed inactivity gap |

Baselines are deterministic trailing averages with configurable lookback and minimum-history eligibility. They are not machine learning.

## Coverage and rule-family matrix

| Monitoring layer | Implemented | Remaining gap |
|---|---|---|
| Merchant | Static and baseline volume, approval and refund behavior | Industry/MCC and onboarding context |
| MID | Static limits, behavior and dormancy | Authoritative activation/suspension state |
| Card | Velocity, retry pattern, watchlist and cross-merchant linkage | Stable network token preferred over PAN-derived hash |
| Customer | Email and phone proxies | Stable customer ID absent |
| Email | Multi-card linkage and watchlist | Email age/verification absent |
| Phone | Normalized multi-card linkage and watchlist | Phone age/verification absent |
| Device/fingerprint | Not executable | Device field absent |
| IP address | Not executable | Source IP absent; GeoIP country alone is insufficient |
| Geography | Country mismatch and configured risk country | Travel history and IP intelligence absent |
| Velocity | Card approvals, declines and decline-to-approval | Customer/device/IP velocity absent |
| Transaction amount | Context, volume baseline and repeated exact amount | Currency normalization and richer structuring logic |
| Status/declines | Counts, approval rate and decline-to-approval | Gateway response-code normalization |
| Merchant baseline | Trailing daily volume and approval rate | Hour/day/country/brand baselines not yet executable |
| Customer baseline | Not executable | Stable customer ID absent |
| Cross-merchant | Card linkage | Customer/device/IP network linkage absent |
| Dormancy | Observed MID inactivity gap | Authoritative MID lifecycle data absent |
| Refund/reversal | Type-based rate baseline | Original-transaction link absent |
| Chargebacks | Not executable | Dispute/chargeback data absent |
| Structuring | Rapid repeated card/amount | Currency-aware near-threshold series remains backlog |
| Transaction linkage | Card, email, phone, merchant and MID | Device, IP and refund graph links absent |
| Data quality | Informational dependency report | Source-system lineage absent |

## Inheritance design

Effective settings resolve in this order:

1. Global defaults
2. Antifraud plan
3. Merchant detailed settings and merchant patch
4. MID detailed settings and MID patch
5. Valid temporary override

The most specific setting wins. Temporary overrides support ID, scope, start, expiry, reason, approval metadata and a values patch. Alert evidence records the effective source in `rule_scope`. Existing plan maps, MID matrices and merchant matrices remain supported.

## Duplicate, conflicting, weak or unusable rules

- The four amount/merchant-value rules duplicated preventive acceptance controls inside TM. They now populate `preventive_control_breaches` only.
- `MERCHANT_DAILY_VOLUME` previously emitted one hit for every transaction in a breached group. It now emits one representative hit per merchant/MID/brand/day.
- Alert scores previously merged on transaction ID and could corrupt duplicate-ID rows. Scoring now joins on normalized row identity.
- Rule toggles previously filtered hits after all rules executed. Eligibility is now checked before alert creation.
- Email/phone linkage still uses the uploaded evaluation period because historical identity storage is not yet available. This limitation is explicit in rule metadata.
- Repeated exact amount remains a weak structuring proxy and must be corroborated with status and retry evidence.
- BIN matches are broad and should not be treated as conclusive without supporting indicators.

## False-positive analysis and controls

Likely concentrations include planned merchant campaigns, seasonal volume changes, family or corporate cards, legitimate travel/VPN activity, gateway retries, shared booking contacts, common BINs and related merchants.

Controls introduced:

- Plan, merchant, MID and expiring temporary thresholds
- Required-field eligibility and data-quality reporting
- Minimum volume/history requirements for baselines
- One representative hit for aggregate daily breaches
- Consolidation of related hits without merging unrelated entity/day groups
- Rule simulation with alert-rate and merchant-concentration warnings
- Rule-level false-positive risks and controls in configuration
- Masked card evidence in alerts and investigation views

Measured false-positive rates remain unavailable until analyst dispositions are stored.

## Reporting audit and refactor

### Before

- Monitoring summary emphasized raw rule hits.
- Alert Queue was a transaction-level table.
- No alert detail, merchant behavior, MID behavior or rule-performance views existed.
- Related indicators were not combined into a risk story.
- Report generation recalculated on each rerun.
- Excel raw/hit sheets were truncated at 50,000 rows.

### After

- Monitoring Run Summary shows transactions, flagged rate, unique cases, severity, top rules, merchants, MIDs and data-quality warnings.
- Alert Queue shows stable alert ID, severity, score, entity, insight, rule count, transaction count, amount, time range and status.
- Alert Detail uses progressive disclosure: risk story, metrics, reasons, baseline, related indicators, timeline, evidence, action and raw rows.
- Merchant Behaviour shows current versus trailing behavior, distributions, trend, MID comparison and linked risks.
- MID Behaviour shows plan, inheritance source, effective thresholds, overrides, behavior and alert cases.
- Rule Performance reports matches, alert rate, volume warning and affected entities.
- Excel exports add investigation alerts, rule performance and data quality while retaining raw rule hits and transactions.
- CSV exports are available for cases, supporting hits and raw normalized transactions.
- Evaluation and report generation use Streamlit caching.

## Rule simulation

Simulation evaluates current and proposed settings on the same upload and returns:

- Transactions evaluated and matched
- Investigation alerts and supporting hits
- Alert rate
- Critical/high/medium/low counts
- Top affected merchants and MIDs
- Merchant concentration as an estimated false-positive concentration proxy
- Current/proposed comparison
- `Review` at 5% match rate and `Excessive` at 20%

These warnings are operational calibration aids, not claims that alerts are false positives.

## Visa-grade benchmark gap analysis

| Area | Current assessment |
|---|---|
| Merchant/MID monitoring | Improved; static, baseline and inheritance coverage present |
| Card/customer velocity | Card coverage present; stable customer ID absent |
| Cross-merchant linkage | Card linkage implemented |
| Device/IP intelligence | Missing data |
| Geographic anomalies | Basic country mismatch/risk-list coverage |
| Behavioral baselines | Volume, approval and refund rate implemented; richer distributions remain |
| Dormancy | Observed-history implementation; lifecycle data absent |
| Transaction laundering | Partial cross-merchant/card and merchant-change indicators |
| Structuring | Weak; repeated exact amount only |
| Refund/reversal abuse | Rate anomaly present; linkage absent |
| Chargeback correlation | Missing data |
| Governance/auditability | Governed metadata and inheritance provenance added; persistent approvals/version history remain |
| Rule testing | Automated regression suite added; production backtest dataset required |
| False-positive management | Simulation and documented controls added; analyst disposition labels absent |
| Alert evidence | Case story, raw hits, linked evidence and raw transactions retained |
| Data quality | Dependency report added; source lineage absent |
| Plan inheritance | Five-level resolution implemented |

## Prioritized backlog

1. Calibrate thresholds on representative production history and alert-heavy 100,000-row datasets.
2. Make one source directory authoritative and remove deployment ambiguity after confirming the external launch path.
3. Persist rule versions, approvals, temporary override history and analyst dispositions.
4. Load prior SQLite transaction history into baseline calculation with run de-duplication.
6. Add stable customer, device, IP, MCC/lifecycle, refund linkage and chargeback fields.
7. Add hour-of-day, day-of-week, country and card-brand distribution baselines.
8. Add currency-aware structuring and threshold-avoidance scenarios.
9. Measure false-positive and detection quality from analyst dispositions.

## Files changed

- `rules.yaml`: governed rule catalogue, preventive catalogue, future-data requirements, baseline settings and temporary overrides.
- `transaction_monitor.py`: safe execution, inheritance, context controls, new scenarios, baselines, cases, simulation, data quality, rule performance and enriched exports.
- `app.py`: investigation views, behavior views, rule performance, simulation, progressive disclosure, caching and exports.
- `tests/test_transaction_monitor.py`: regression tests.
- `requirements.txt`: pytest test dependency.
- `TM_AUDIT_AND_REFACTOR.md`: audit and implementation record.

The same functional files are synchronized to the nested `payouts_tm_mvp` copy because both layouts existed before this refactor.

## Test status and remaining limitations

Automated tests cover governance schema, preventive/TM separation, inheritance priority, duplicate transaction IDs, masked card evidence, baseline eligibility, simulation comparison and enriched export preservation. Result: **7 passed**.

A synthetic 100,000-row benchmark completed in **37.78 seconds** at **2,647 rows/second**, producing 70 rule hits and 70 investigation alerts. This supports the approximate file-based usability target with Streamlit caching, but alert-heavy real-world files and report generation require separate production-volume calibration.

The application remains an MVP: it has no formal case-management workflow, user roles, external intelligence, real-time decisioning or formal Visa certification.
