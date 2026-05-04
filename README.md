# Stima SACCO Portfolio Intelligence

**A SASRA-constraint-aware early-warning system for member default risk, built to surface contribution gap and withdrawal surge signals 60-90 days before PAR30 breaches appear in regulatory filings.**

---

## Business Context

Stima SACCO manages a loan portfolio across 600+ members in Kenya, reporting quarterly to SASRA under the SACCO Societies Act. The Head of Research and Innovation needs analytics that do three things: identify which members are heading toward PAR30 before the monthly provisioning cycle, ensure the SACCO stays inside four SASRA regulatory constraints, and produce a ranked weekly intervention list that Relationship Officers can execute without further analysis. The contribution gap signal appears 60-90 days before a PAR30 breach, which is exactly the window needed to make a wellness call, restructure a payment schedule, or offer an emergency product before the loan sours.

The operating constraints matter because a recommendation to increase loan disbursements to a member with a 95% propensity score is operationally correct and regulatorily wrong if it pushes the loan-to-deposit ratio above 80% or the liquid asset ratio below 10%. A SASRA breach can result in suspension of new business, regulatory penalties, and member confidence damage. Every recommendation in this system is checked against all four hard constraints before it reaches the Relationship Officer.

---

## The Analytical Question

Does the days_since_last_contribution signal (relative to tier-specific thresholds of 30, 45, and 60 days) reliably precede a PAR30 breach, and if so, how much in SASRA provisions can be avoided with a timely Relationship Officer intervention?

---

## What I Found

1. **PAR30 Rate:** The current PAR30 rate across the portfolio is approximately 2.33% at baseline, with the HIGH propensity band showing a confirmation rate of 64.72%, representing a lift of 27.73x over the baseline. PAR30 varies by tier, with Standard and Basic members showing higher rates than Premium members.

2. **Leading Indicator:** 8.95% of days_since_last_contribution values are missing, which requires ETL remediation before the signal can be fully trusted. 62.16% of AT-RISK members have a NULL last_actioned_date, confirming that CRM action tracking is the primary process gap to close. The signal (days >= 45) has crossed the flat portfolio threshold in multiple periods over the 24-month dataset.

3. **Lead-Lag Relationship:** The contribution gap signal precedes a confirmed PAR30 breach by approximately 3 monthly periods (60-90 days). Confirmation rate: approximately 64%. False positive rate: approximately 36%. In SACCO lending, the cost of an unnecessary wellness call (KES 500 in Relationship Officer time) is 160 times less than a missed PAR30 provision (~KES 80,000 per loan).

4. **Cost of Inaction:** With a 50% recovery rate [ASSUMPTION] and the current AT-RISK cohort, the recoverable provision across tiers is several million KES. This figure requires validation against Stima SACCO's historical CRM call-to-recovery records in the first 6 months of deployment.

5. **Constraint Compliance:** 4 constraints monitored (3 hard SASRA, 1 soft internal policy). The liquid asset ratio (min 8.51%) is currently in BREACH of the SASRA 10% floor. The loan-to-deposit ratio (max 87.89%) is in BREACH of the SASRA 80% ceiling. The single-borrower concentration limit is COMPLIANT at 3.12%. Leaving the liquid asset ratio breach unresolved for one additional month risks regulatory notification to SASRA and possible suspension of new loan disbursements.

---

## What I Recommended

Relationship Officers must contact all members where days_since_last_contribution crosses the tier-specific threshold (30 days Premium, 45 days Standard/Basic) within 5 working days, using the rule engine's priority-ranked list of 80 contacts per week. Simultaneously, Treasury must rebalance liquid assets above 10% within 2 working days and the Credit team must pause new disbursements until the LTD ratio falls below 80%. Success metric: AT-RISK count returns to zero within 60 days and all SASRA constraints return to COMPLIANT within 5 working days.

---

## How to Run the Project

1. `pip install pandas numpy scikit-learn streamlit altair`
2. `python generate_data.py` — produces members.csv, monthly_contributions.csv, loan_book.csv, product_performance.csv, and member_scored.csv (includes propensity model scoring and audit block).
3. `python rule_engine.py` — produces rule_engine_output.csv with priority-ranked weekly intervention list for 80 Relationship Officer contacts.
4. `streamlit run dashboard.py` — opens the interactive SACCO portfolio intelligence dashboard at http://localhost:8501.

---

## Project Structure

```
stima_sacco_portfolio/
├── generate_data.py          # Synthetic data generation + Step 7 logistic regression model
├── rule_engine.py            # Step 8 business rule engine (5 rules, SASRA-aware)
├── dashboard.py              # Step 4 Streamlit dashboard (7 outputs)
├── sql_queries.sql           # Step 3 all 8 SQL queries (PostgreSQL)
├── interview_prep.md         # Step 6 interview preparation document
├── README.md                 # This file
├── members.csv               # Primary entity table (600 members)
├── monthly_contributions.csv # Monthly contribution + compliance data (14,400 rows, 24 months)
├── loan_book.csv             # Loan-level detail with PAR flags (669 loans)
├── product_performance.csv   # Product-level aggregation (120 rows)
├── member_scored.csv         # Propensity model output with risk bands
└── rule_engine_output.csv    # Priority-ranked intervention list (current period)
```

---

## Leading vs Lagging Indicator Reference Table

| Indicator | Type | Current value | Threshold | Lead time | Lagging outcome predicted | Action triggered |
|---|---|---|---|---|---|---|
| days_since_last_contribution | Leading | ~15 days avg (healthy cohort) | Premium: 30 days / Standard: 45 days / Basic: 60 days | 60-90 days (3 months) | PAR30 breach | Relationship Officer contact within 5 working days |
| withdrawal_surge_index | Leading | ~1.1 avg (healthy cohort) | >= 2.0 (double normal rate) | 30-45 days (1-2 months) | Savings balance deterioration | Branch Manager financial wellness call within 3 days |
| payroll_confirmation_lag_days | Leading | ~5 days avg | >= 15 days (late payroll deduction) | 30-60 days | Contribution gap widening | Employer liaison contact within 3 working days |
| PAR30 rate | Lagging | 2.33% baseline | 5.0% (SASRA guidance) | Confirmed outcome | SASRA provisioning charge | Collections escalation / Credit Committee review |
| Total savings (KES M) | Lagging | Portfolio-level monthly total | 2% monthly growth target | Confirmed outcome | Liquidity ratio deterioration | Treasury rebalancing action |

---

## Constraint Compliance Reference Table

| Constraint | Type | Current value | Limit | Headroom/Breach | Source | Consequence if violated |
|---|---|---|---|---|---|---|
| SASRA Liquid Asset Ratio | Regulatory (Hard) | 8.51% | 10.0% | -1.49pp BREACH | SASRA Act / SACCO regulations | Regulatory sanction, disbursement suspension |
| SASRA Loan-to-Deposit Ratio | Regulatory (Hard) | 87.89% | 80.0% | -7.89pp BREACH | SASRA Act | Suspension of new loan approvals, regulatory penalty |
| SASRA Single-Borrower Limit | Concentration (Hard) | 3.12% | 10.0% | +6.88pp headroom | SASRA single-borrower rules | Credit concentration risk, regulatory action |
| Preferred Liquid Ratio | Internal Policy (Soft) | 8.51% | 15.0% | -6.49pp below preferred | Board internal policy | Management review, tightened credit approval |

---

## Analytics Layers Covered

| Layer | Output / File | Output type | Business question | Indicator type |
|---|---|---|---|---|
| Descriptive | Output 1 (dashboard) | Chart + Table | How has PAR30 moved by tier over 24 months? | Lagging |
| Descriptive | Query 6 (SQL) | Table | What is the current value and pace of every tracked KPI? | Both |
| Descriptive | Query 8 (SQL) | Table | Are all SASRA constraints within limits right now? | Compliance |
| Diagnostic | Output 3 (dashboard) | Chart | Does the leading indicator reliably precede PAR30? | Both |
| Diagnostic | Query 4 (SQL) | Table | Which members deteriorated to a worse segment this month? | Leading |
| Predictive | Output 2 (dashboard) | Chart | Which members have crossed the contribution gap threshold? | Leading |
| Predictive | member_scored.csv | Table | What is each member's probability of PAR30 breach in 90 days? | Leading |
| Prescriptive | Output 5 (dashboard) | Chart | How much provision is recoverable if the signal is acted on? | Leading + Lagging |
| Prescriptive | rule_engine_output.csv | Table | Which 80 members should the team contact this week, and in what order? | Both |

---

## Skills Demonstrated

**Technical**
| Skill | JD mapping |
|---|---|
| Window functions (LAG, LEAD, RANK, running totals) with date normalisation | SQL / Oracle proficiency; data mining techniques; query writing |
| Logistic regression with class_weight='balanced', time-based train-test split, and AUC evaluation | Statistical / predictive modelling; Python proficiency |
| Multi-CTE data cleaning pipeline (mixed date formats, missing values, FK violations) | Data integrity, quality, and governance; ETL frameworks |
| SASRA-constraint-bounded rule engine with priority ranking and capacity limits | Risk management; knowledge of SACCO regulatory environment |
| Streamlit dashboard with leading/lagging toggle, always-visible compliance cards | Reporting tools; data visualisation; stakeholder-facing output |

**Business**
| Skill | Decision supported |
|---|---|
| Early-warning framework (60-90 days before PAR30) | Head of Research: which members require intervention before the quarterly SASRA filing |
| SASRA constraint compliance monitoring | Board and SASRA examiner: is the SACCO inside all regulatory limits right now |
| Tiered member segmentation by contribution behaviour and loan exposure | Relationship Officer team: ranked weekly call list with specific contact reason |
| Cost-of-inaction quantification in KES | CEO/Board: financial case for Relationship Officer capacity investment |
| SPPY-adjusted period comparison | Monthly board pack: is PAR30 seasonal or genuinely deteriorating |
