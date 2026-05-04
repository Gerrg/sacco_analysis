"""
Stima SACCO - Data Analyst Portfolio
generate_data.py

Produces all CSV files consumed by dashboard.py, rule_engine.py, and the
propensity model embedded at the end of this file.

Run: python generate_data.py

Output files:
  members.csv              - Primary entity table: 600 SACCO members
  monthly_contributions.csv - Monthly contribution and loan activity, 24 months
  loan_book.csv            - Loan-level detail with repayment status
  product_performance.csv  - Product-level aggregation by month

STEP 1A: ROLE ANALYSIS
=======================
3 CORE BUSINESS PROBLEMS:
1. Identify members at risk of loan default before PAR30 is breached,
   using contribution gap and withdrawal surge as leading indicators.
   [PREDICTIVE layer]
2. Forecast monthly contribution inflows to support liquidity planning
   and ensure the regulatory 15% liquid asset ratio is maintained.
   [PREDICTIVE layer]
3. Reduce delinquency-driven provisioning costs by prescribing early
   intervention actions ranked by expected recovery value.
   [PRESCRIPTIVE layer]

All four analytics layers are present:
- Descriptive:  Portfolio health dashboard, contribution trend reporting
- Diagnostic:   PAR30 root-cause segmentation, withdrawal-surge diagnosis
- Predictive:   Default propensity model, contribution forecast
- Prescriptive: Rule engine - ranked intervention list within capacity

LEADING INDICATORS (Step 1A):
1. days_since_last_contribution
   Leads PAR30 breach by approximately 60-90 days (2-3 months).
   Actionable threshold: 45 days portfolio-wide; 30 days for Premium members.
   Who acts: Relationship Officer contacts the member within 5 working days.
   Tiered threshold: Premium: 30 days / Standard: 45 days / Basic: 60 days.

2. withdrawal_surge_index  (withdrawals this month / average withdrawals last 3 months)
   Leads savings balance deterioration by approximately 30-45 days (1-2 months).
   Actionable threshold: index >= 2.0 (double the normal withdrawal rate).
   Who acts: Branch Manager initiates financial wellness call within 3 working days.

LAGGING INDICATORS:
- PAR30_pct (portfolio at risk > 30 days): confirmed delinquency outcome
- savings_balance_kes: confirmed liquidity outcome

HARD CONSTRAINTS (Step 1B):
1. SASRA Regulatory - Liquid Asset Ratio: must be >= 10% of total assets.
   Source: SACCO Societies Regulatory Authority (SASRA) Act.
2. SASRA Regulatory - Core Capital Ratio: must be >= 10% of total assets.
3. Concentration limit: no single member's loan balance may exceed 10% of
   the total loan book (SASRA single-borrower limit).
4. Liquidity constraint: loan-to-deposit ratio must not exceed 80%.

SOFT CONSTRAINTS:
1. Preferred liquid asset ratio: >= 15% (internal SACCO policy, above the
   SASRA 10% floor). Triggers management review if it falls to 12-15%.
2. Provision coverage ratio: >= 60% of PAR30 balance. Triggers board review
   if it falls below 50%.
"""

import numpy as np
import pandas as pd
from datetime import date, timedelta
import random
import warnings
warnings.filterwarnings('ignore')

np.random.seed(99)
random.seed(99)

# ---- CONFIGURATION ----
N_MEMBERS = 600
START_DATE = date(2023, 1, 1)
END_DATE   = date(2024, 12, 31)   # 24 months exactly

PRODUCTS = ['Home Loan', 'Business Loan', 'Emergency Loan', 'School Fees Loan', 'Normal Savings']
MEMBER_TIERS = {
    'Premium':  {'count': 90,  'base_savings': 250_000, 'base_loan': 800_000,  'contrib_floor': 5_000,  'threshold_days': 30},
    'Standard': {'count': 300, 'base_savings': 80_000,  'base_loan': 250_000,  'contrib_floor': 2_000,  'threshold_days': 45},
    'Basic':    {'count': 210, 'base_savings': 20_000,  'base_loan': 80_000,   'contrib_floor': 500,    'threshold_days': 60},
}
BRANCHES = ['Nairobi HQ', 'Westlands', 'Mombasa Road', 'Thika', 'Nakuru']


# ============================================================
# TABLE 1: members  (primary entity, N_MEMBERS rows)
# ============================================================
def build_members():
    records = []
    mid = 1
    for tier, cfg in MEMBER_TIERS.items():
        for i in range(cfg['count']):
            branch = random.choice(BRANCHES)
            employer = random.choice(['Kenya Power', 'KPLC Subsidiary', 'County Govt',
                                      'Parastatals', 'Private Sector', 'Self Employed'])
            records.append({
                'member_id':              f'STM{mid:05d}',
                'tier':                   tier,
                'branch':                 branch,
                'employer_category':      employer,
                'join_date':              (date(2010, 1, 1) + timedelta(days=random.randint(0, 4000))).isoformat(),
                'credit_limit_kes':       round(cfg['base_loan'] * np.random.uniform(0.5, 2.0), -3),
                'monthly_contrib_kes':    round(cfg['contrib_floor'] * np.random.uniform(1.0, 4.0), -2),
                'single_borrower_limit_pct': 10.0,   # CONSTRAINT column
                'preferred_liquid_ratio_pct': 15.0,  # CONSTRAINT column (soft)
            })
            mid += 1
    df = pd.DataFrame(records)
    return df


# ============================================================
# TABLE 2: monthly_contributions  (24 months x 600 members = 14,400 rows)
# ============================================================
def build_contributions(members_df):
    records = []
    months = pd.date_range(start=START_DATE, end=END_DATE, freq='MS')

    # Designate ~8% of members as 'at-risk' (will show deteriorating signals)
    at_risk_ids = set(members_df.sample(frac=0.08, random_state=42)['member_id'])
    # Another 5% show withdrawal surge
    surge_ids = set(members_df.sample(frac=0.05, random_state=7)['member_id'])

    for _, mbr in members_df.iterrows():
        base_contrib = mbr['monthly_contrib_kes']
        tier = mbr['tier']
        declining = mbr['member_id'] in at_risk_ids
        surging   = mbr['member_id'] in surge_ids

        savings = mbr['credit_limit_kes'] * 0.4   # opening balance

        for m_idx, snap_date in enumerate(months):
            # Contribution patterns
            if declining and m_idx >= 14:
                contrib = base_contrib * np.random.uniform(0.0, 0.3)   # near-zero contributions
                days_since_contrib = int(np.random.uniform(46, 120))
            else:
                contrib = base_contrib * np.random.uniform(0.85, 1.15)
                days_since_contrib = int(np.random.uniform(1, 28))

            # Savings balance
            savings = max(0, savings + contrib - np.random.uniform(0, contrib * 0.6))

            # Withdrawal surge index
            if surging and m_idx >= 10:
                withdrawal_surge_index = round(np.random.uniform(2.1, 4.5), 2)
            else:
                withdrawal_surge_index = round(np.random.uniform(0.4, 1.8), 2)

            # PAR30 flag (lagging outcome - reflects months of declining contribution)
            par30_breach = (declining and m_idx >= 17)

            # Loan outstanding
            loan_outstanding = mbr['credit_limit_kes'] * np.random.uniform(0.3, 0.95)

            # DQ: missing values in days_since_last_contribution (~9%) and savings_balance (~6%)
            dsc_dq = days_since_contrib if random.random() > 0.09 else np.nan
            sav_dq = round(savings, 2) if random.random() > 0.06 else np.nan

            # last_actioned_date: NULL for ~62% of entities (incomplete CRM)
            if random.random() > 0.38:
                last_actioned_date = None
            else:
                days_ago = random.randint(1, 90)
                last_actioned_date = (snap_date.date() - timedelta(days=days_ago)).isoformat()

            # Date format DQ issue: inconsistent format in raw column
            if m_idx % 6 == 0:
                snapshot_date_raw = snap_date.strftime('%d/%m/%Y')
            else:
                snapshot_date_raw = snap_date.strftime('%Y-%m-%d')

            # Outlier: one member has a single enormous contribution (data entry error)
            if mbr['member_id'] == 'STM00001' and m_idx == 4:
                contrib = contrib * 120   # > 3 SD outlier

            # Referential integrity issue: one orphaned FK
            member_id_fk = mbr['member_id']
            if mbr['member_id'] == 'STM00600' and m_idx == 8:
                member_id_fk = 'STM99999'

            # Payroll confirmation lag (leading indicator proxy)
            payroll_confirmation_lag_days = int(np.random.uniform(0, 10)) if not declining else int(np.random.uniform(15, 45))

            records.append({
                'member_id':                      member_id_fk,
                'snapshot_date':                  snap_date.date().isoformat(),
                'snapshot_date_raw':              snapshot_date_raw,
                'report_month':                   snap_date.to_period('M').to_timestamp().date().isoformat(),
                'tier':                           tier,
                'monthly_contribution_kes':       round(contrib, 2),
                'days_since_last_contribution':   dsc_dq,           # LEADING INDICATOR (DQ: ~9% missing)
                'withdrawal_surge_index':         withdrawal_surge_index,  # LEADING INDICATOR
                'payroll_confirmation_lag_days':  payroll_confirmation_lag_days,  # LEADING INDICATOR
                'savings_balance_kes':            sav_dq,
                'loan_outstanding_kes':           round(loan_outstanding, 2),
                'par30_breach_flag':              int(par30_breach),    # LAGGING OUTCOME
                'last_actioned_date':             last_actioned_date,
                # CONSTRAINT columns
                'regulatory_liquid_ratio_pct':   round(np.random.uniform(8.5, 22.0), 2),
                'loan_to_deposit_ratio_pct':      round(np.random.uniform(55.0, 88.0), 2),
            })

    return pd.DataFrame(records)


# ============================================================
# TABLE 3: loan_book  (one row per active loan, ~800 loans)
# ============================================================
def build_loan_book(members_df):
    records = []
    loan_id = 1
    for _, mbr in members_df.iterrows():
        n_loans = random.choices([0, 1, 2], weights=[0.15, 0.60, 0.25])[0]
        for _ in range(n_loans):
            product = random.choice(PRODUCTS[:4])
            principal = round(mbr['credit_limit_kes'] * np.random.uniform(0.3, 0.9), -3)
            disbursed = (date(2022, 1, 1) + timedelta(days=random.randint(0, 700))).isoformat()
            tenor_months = random.choice([12, 24, 36, 48, 60])
            outstanding = round(principal * np.random.uniform(0.1, 0.95), -3)
            days_past_due = int(np.random.exponential(20))
            records.append({
                'loan_id':              f'LN{loan_id:06d}',
                'member_id':           mbr['member_id'],
                'product_type':        product,
                'principal_kes':       principal,
                'outstanding_kes':     outstanding,
                'disbursement_date':   disbursed,
                'tenor_months':        tenor_months,
                'days_past_due':       days_past_due,
                'par30_flag':          int(days_past_due > 30),
                'concentration_pct':   0.0,  # filled after aggregation
                'single_borrower_limit_pct': 10.0,  # CONSTRAINT column
            })
            loan_id += 1

    df = pd.DataFrame(records)
    total_book = df['outstanding_kes'].sum()
    df['concentration_pct'] = df.groupby('member_id')['outstanding_kes'].transform('sum') / total_book * 100
    return df


# ============================================================
# TABLE 4: product_performance  (5 products x 24 months = 120 rows)
# ============================================================
def build_product_performance():
    records = []
    months = pd.date_range(start=START_DATE, end=END_DATE, freq='MS')
    product_base = {
        'Home Loan': 850_000_000, 'Business Loan': 420_000_000,
        'Emergency Loan': 120_000_000, 'School Fees Loan': 200_000_000,
        'Normal Savings': 1_500_000_000
    }
    for snap_date in months:
        for prod, base in product_base.items():
            records.append({
                'snapshot_date':  snap_date.date().isoformat(),
                'product':        prod,
                'balance_kes':    round(base * np.random.uniform(0.92, 1.08), -3),
                'par30_pct':      round(np.random.uniform(1.5, 8.5), 2),
                'members_count':  random.randint(60, 400),
                'avg_yield_pct':  round(np.random.uniform(9.0, 15.0), 2),
                'npl_provision_kes': round(base * np.random.uniform(0.005, 0.04), -3),
            })
    return pd.DataFrame(records)


# ============================================================
# GENERATE AND SAVE
# ============================================================
members_df      = build_members()
contributions_df = build_contributions(members_df)
loan_book_df    = build_loan_book(members_df)
product_perf_df = build_product_performance()

members_df.to_csv('members.csv', index=False)
contributions_df.to_csv('monthly_contributions.csv', index=False)
loan_book_df.to_csv('loan_book.csv', index=False)
product_perf_df.to_csv('product_performance.csv', index=False)

print("CSVs written: members, monthly_contributions, loan_book, product_performance")
print(f"  members:               {len(members_df):,} rows")
print(f"  monthly_contributions: {len(contributions_df):,} rows")
print(f"  loan_book:             {len(loan_book_df):,} rows")
print(f"  product_performance:   {len(product_perf_df):,} rows")


# ============================================================
# STEP 7: PROPENSITY SCORE MODEL
#
# Model selection: Logistic Regression
# Outcome: par30_breach_flag (binary: 1 = loan past due > 30 days)
# Reason: The outcome is a binary event (PAR30 breach). Logistic regression
# produces a 0-to-1 probability interpretable as "probability of default in
# the next 30 days." Coefficients show which features increase or reduce risk,
# which is explainable to the Head of Research and the SACCO board in under
# 60 seconds: "each additional day since the last contribution raises default
# probability by X." Alternative considered: decision tree (max depth 4).
# Logistic regression chosen because SASRA reporting requires auditable model
# documentation; a printed coefficient table satisfies that requirement more
# cleanly than a decision tree diagram.
# Switch condition: if outcome rate drops below 3%, use SMOTE + gradient boosting.
# ============================================================
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix
import warnings
warnings.filterwarnings('ignore')

print("\n--- STEP 7: DEFAULT PROPENSITY MODEL ---")

contrib = contributions_df.copy()
contrib = contrib.merge(
    members_df[['member_id', 'tier', 'credit_limit_kes', 'monthly_contrib_kes',
                'single_borrower_limit_pct']],
    on='member_id', how='left', suffixes=('', '_mbr')
)
# Use the member-table tier if the contributions tier is missing
if 'tier_mbr' in contrib.columns:
    contrib['tier'] = contrib['tier'].fillna(contrib['tier_mbr'])
    contrib.drop(columns=['tier_mbr'], inplace=True)

# Keep only valid members (exclude orphaned FK row)
valid_ids = set(members_df['member_id'])
contrib = contrib[contrib['member_id'].isin(valid_ids)]

contrib['snapshot_date'] = pd.to_datetime(contrib['snapshot_date'])
contrib = contrib.sort_values(['member_id', 'snapshot_date'])

# Fill missing values with column median before modelling
# Median is appropriate because it is robust to the embedded outliers in contrib data
for col in ['days_since_last_contribution', 'savings_balance_kes']:
    contrib[col] = contrib[col].fillna(contrib[col].median())

# Feature engineering
tier_map = {'Premium': 2, 'Standard': 1, 'Basic': 0}
contrib['tier_encoded'] = contrib['tier'].map(tier_map)

contrib['contrib_to_limit_ratio'] = (
    contrib['monthly_contribution_kes'] /
    contrib['credit_limit_kes'].replace(0, np.nan)
).fillna(0).clip(0, 10)

contrib['savings_to_loan_ratio'] = (
    contrib['savings_balance_kes'] /
    contrib['loan_outstanding_kes'].replace(0, np.nan)
).fillna(0).clip(0, 20)

contrib['revenue_normalised'] = contrib.groupby('tier')['monthly_contribution_kes'].transform(
    lambda x: (x - x.mean()) / (x.std() + 1e-9)
)

FEATURES = [
    'days_since_last_contribution',    # LEADING INDICATOR 1
    'withdrawal_surge_index',          # LEADING INDICATOR 2
    'payroll_confirmation_lag_days',   # LEADING INDICATOR 3
    'savings_balance_kes',             # MODEL FEATURE
    'loan_outstanding_kes',            # MODEL FEATURE
    'contrib_to_limit_ratio',          # MODEL FEATURE
    'savings_to_loan_ratio',           # MODEL FEATURE
    'regulatory_liquid_ratio_pct',     # CONSTRAINT metric - MODEL FEATURE
    'tier_encoded',
]

model_df = contrib[FEATURES + ['par30_breach_flag', 'snapshot_date', 'member_id',
                                'tier', 'monthly_contribution_kes',
                                'days_since_last_contribution', 'withdrawal_surge_index',
                                'loan_outstanding_kes', 'savings_balance_kes',
                                'single_borrower_limit_pct']].dropna()

# Time-based train-test split - do NOT use random split.
# A random split would place Dec 2024 data in training and Jan 2023 in test,
# allowing the model to learn future default confirmations it should not know yet.
cutoff = model_df['snapshot_date'].quantile(0.80)
train = model_df[model_df['snapshot_date'] <= cutoff]
test  = model_df[model_df['snapshot_date'] >  cutoff]

X_train, y_train = train[FEATURES], train['par30_breach_flag']
X_test,  y_test  = test[FEATURES],  test['par30_breach_flag']

outcome_rate = y_train.mean()
print(f"Outcome rate (PAR30 breach in training set): {outcome_rate:.2%}")

# class_weight='balanced': without it, a model on 92%+ non-events learns to
# predict 0 for everything and catches zero defaulters.
pipe = Pipeline([
    ('scaler', StandardScaler()),
    ('model', LogisticRegression(class_weight='balanced', max_iter=1000, random_state=99))
])
pipe.fit(X_train, y_train)

y_prob = pipe.predict_proba(X_test)[:, 1]
y_pred = pipe.predict(X_test)
auc    = roc_auc_score(y_test, y_prob)

print(f"\nTest AUC-ROC:  {auc:.3f}")
print("\nClassification Report:")
print(classification_report(y_test, y_pred, zero_division=0))
print("Confusion Matrix:")
print(confusion_matrix(y_test, y_pred))

# Feature importance (standardised coefficients)
coef = pipe.named_steps['model'].coef_[0]
feat_imp = sorted(zip(FEATURES, coef), key=lambda x: abs(x[1]), reverse=True)
print("\nFeature Coefficients (sorted by |coef|):")
for feat, c in feat_imp:
    direction = "INCREASES default risk" if c > 0 else "reduces default risk"
    print(f"  {feat:40s}  {c:+.3f}  ({direction})")
# If leading indicators rank in the top 3 by |coef|, two separate analytical
# methods (domain-knowledge thresholds AND the data-driven model) have
# independently confirmed the same signals.

# Score all entities
full = model_df.copy()
full['default_propensity_score'] = (pipe.predict_proba(full[FEATURES])[:, 1] * 100).round(1)

# Risk bands: HIGH >60, MEDIUM 30-60, LOW <30
# [ASSUMPTION] Boundaries set so HIGH contains 15-25% of members.
# Recalibrate against actual historical PAR30 confirmation rates in Q1 of deployment.
def assign_band(s):
    if s >= 60: return 'HIGH'
    if s >= 30: return 'MEDIUM'
    return 'LOW'

full['risk_band'] = full['default_propensity_score'].apply(assign_band)

# Step 7B: Constraint override filter
# Check single-borrower concentration limit (10%) before recommending loan top-ups
loan_exposure = loan_book_df.groupby('member_id')['outstanding_kes'].sum()
total_book    = loan_book_df['outstanding_kes'].sum()
exposure_pct  = (loan_exposure / total_book * 100).rename('exposure_pct')
full = full.merge(exposure_pct, on='member_id', how='left')
full['exposure_pct'] = full['exposure_pct'].fillna(0)

full['constraint_override'] = (full['exposure_pct'] > full['single_borrower_limit_pct']).astype(bool)
full['constraint_override_reason'] = full['constraint_override'].apply(
    lambda x: (
        "Single-borrower concentration limit breach: this member's loan balance "
        "exceeds 10% of the total loan book. Any top-up or restructure must be "
        "approved by the Credit Committee before the Relationship Officer can act."
    ) if x else ""
)

# Score distribution
band_counts = full['risk_band'].value_counts()
high_rate   = full[full['risk_band'] == 'HIGH']['par30_breach_flag'].mean()
base_rate   = full['par30_breach_flag'].mean()
lift        = high_rate / base_rate if base_rate > 0 else 0

print(f"\nRisk band distribution:\n{band_counts}")
print(f"HIGH band PAR30 confirmation rate: {high_rate:.2%}")
print(f"Baseline PAR30 rate:               {base_rate:.2%}")
print(f"Lift (HIGH vs baseline):           {lift:.2f}x")

score_cols = ['member_id', 'snapshot_date', 'tier', 'monthly_contribution_kes',
              'days_since_last_contribution', 'withdrawal_surge_index',
              'par30_breach_flag', 'default_propensity_score', 'risk_band',
              'constraint_override', 'constraint_override_reason',
              'loan_outstanding_kes', 'savings_balance_kes', 'exposure_pct']
full[score_cols].to_csv('member_scored.csv', index=False)
print("\nSaved: member_scored.csv")


# ============================================================
# AUDIT BLOCK
# ============================================================
audit = {}

# Row counts
audit['table.members.row_count']               = len(members_df)
audit['table.monthly_contributions.row_count'] = len(contributions_df)
audit['table.loan_book.row_count']             = len(loan_book_df)
audit['table.product_performance.row_count']   = len(product_perf_df)

# DQ Issue 1: Missing values
total = len(contributions_df)
dsc_miss = contributions_df['days_since_last_contribution'].isna().sum()
sav_miss = contributions_df['savings_balance_kes'].isna().sum()
audit['table.monthly_contributions.days_since_last_contribution.missing_count'] = int(dsc_miss)
audit['table.monthly_contributions.days_since_last_contribution.missing_pct']   = round(dsc_miss/total*100, 2)
audit['table.monthly_contributions.savings_balance_kes.missing_count']          = int(sav_miss)
audit['table.monthly_contributions.savings_balance_kes.missing_pct']            = round(sav_miss/total*100, 2)

# DQ Issue 2: Outlier
rev_m = contributions_df['monthly_contribution_kes'].mean()
rev_s = contributions_df['monthly_contribution_kes'].std()
outlier_ct = (contributions_df['monthly_contribution_kes'] > rev_m + 3*rev_s).sum()
audit['table.monthly_contributions.monthly_contribution_kes.outlier_count']     = int(outlier_ct)
audit['table.monthly_contributions.monthly_contribution_kes.outlier_threshold'] = round(rev_m + 3*rev_s, 2)

# DQ Issue 3: Mixed date format
mixed = contributions_df['snapshot_date_raw'].str.contains('/').sum()
audit['table.monthly_contributions.snapshot_date_raw.mixed_format_count'] = int(mixed)
audit['table.monthly_contributions.snapshot_date_raw.mixed_format_pct']   = round(mixed/total*100, 2)

# DQ Issue 4: Referential integrity
orphaned = contributions_df[~contributions_df['member_id'].isin(members_df['member_id'])]
audit['table.monthly_contributions.member_id.orphaned_fk_count'] = int(len(orphaned))

# last_actioned_date completeness for AT-RISK members
at_risk_rows = contributions_df[
    contributions_df['days_since_last_contribution'].fillna(0) >= 45
]
null_action_pct = at_risk_rows['last_actioned_date'].isna().mean() * 100
audit['table.monthly_contributions.at_risk_members.null_last_actioned_date_pct'] = round(null_action_pct, 2)

# Leading indicator distributions
audit['leading_indicator.days_since_last_contribution.describe'] = (
    contributions_df['days_since_last_contribution'].describe().round(2).to_dict()
)
audit['leading_indicator.withdrawal_surge_index.describe'] = (
    contributions_df['withdrawal_surge_index'].describe().round(2).to_dict()
)

# Constraint compliance (latest month)
latest = contributions_df['snapshot_date'].max()
latest_contrib = contributions_df[contributions_df['snapshot_date'] == latest]
min_liquid = latest_contrib['regulatory_liquid_ratio_pct'].min()
max_ltd    = latest_contrib['loan_to_deposit_ratio_pct'].max()
loan_total = loan_book_df['outstanding_kes'].sum()
max_conc   = loan_book_df.groupby('member_id')['outstanding_kes'].sum().max() / loan_total * 100

audit['constraint.liquid_asset_ratio.min_pct']    = round(min_liquid, 2)
audit['constraint.liquid_asset_ratio.status']     = 'COMPLIANT' if min_liquid >= 10 else 'BREACH'
audit['constraint.loan_to_deposit_ratio.max_pct'] = round(max_ltd, 2)
audit['constraint.loan_to_deposit_ratio.status']  = 'COMPLIANT' if max_ltd <= 80 else 'BREACH'
audit['constraint.single_borrower_limit.max_pct'] = round(max_conc, 2)
audit['constraint.single_borrower_limit.status']  = 'COMPLIANT' if max_conc <= 10 else 'BREACH'

# Model metrics
audit['model.auc_roc']                     = round(auc, 3)
audit['model.outcome_rate_train']          = round(outcome_rate, 4)
audit['model.lift_high_band']              = round(lift, 2)
audit['model.risk_band_HIGH_count']        = int(band_counts.get('HIGH', 0))
audit['model.risk_band_MEDIUM_count']      = int(band_counts.get('MEDIUM', 0))
audit['model.risk_band_LOW_count']         = int(band_counts.get('LOW', 0))

print("\n===== AUDIT BLOCK =====")
for k, v in audit.items():
    if not isinstance(v, dict):
        print(f"  {k}: {v}")

print("\n===== DATA QUALITY SUMMARY =====")
print(f"  Missing: days_since_last_contribution  {audit['table.monthly_contributions.days_since_last_contribution.missing_pct']}%")
print(f"  Missing: savings_balance_kes           {audit['table.monthly_contributions.savings_balance_kes.missing_pct']}%")
print(f"  Outliers in monthly_contribution_kes:  {audit['table.monthly_contributions.monthly_contribution_kes.outlier_count']} rows")
print(f"  Mixed date formats:                    {audit['table.monthly_contributions.snapshot_date_raw.mixed_format_count']} rows ({audit['table.monthly_contributions.snapshot_date_raw.mixed_format_pct']}%)")
print(f"  Orphaned FK rows:                      {audit['table.monthly_contributions.member_id.orphaned_fk_count']}")
print(f"  AT-RISK with NULL last action:         {audit['table.monthly_contributions.at_risk_members.null_last_actioned_date_pct']}%")

print("\n===== CONSTRAINT COMPLIANCE =====")
print(f"  Liquid Asset Ratio (>=10%):     min={audit['constraint.liquid_asset_ratio.min_pct']}%  STATUS={audit['constraint.liquid_asset_ratio.status']}")
print(f"  Loan-to-Deposit Ratio (<=80%):  max={audit['constraint.loan_to_deposit_ratio.max_pct']}%  STATUS={audit['constraint.loan_to_deposit_ratio.status']}")
print(f"  Single-Borrower Limit (<=10%):  max={audit['constraint.single_borrower_limit.max_pct']}%  STATUS={audit['constraint.single_borrower_limit.status']}")

print("\ngenerate_data.py complete.")
