"""
Stima SACCO - Data Analyst Portfolio
rule_engine.py

Reads the scored output from generate_data.py and applies the five business
rules from Step 1B, ranks members by intervention priority, enforces team
capacity, and writes rule_engine_output.csv.

Run after generate_data.py:
    python rule_engine.py

BUSINESS RULES (from Step 1B Question 4)
------------------------------------------
Rule 1: Contribution Gap Alert
  Trigger: days_since_last_contribution >= tier threshold (Premium 30, Standard 45, Basic 60)
  Action: Relationship Officer contacts member within 5 working days.
  Constraint: Sequencing constraint (contact before PAR30 is confirmed).

Rule 2: Withdrawal Surge Alert
  Trigger: withdrawal_surge_index >= 2.0 for any member in any period
  Action: Branch Manager initiates financial wellness call within 3 working days.
  Constraint: Liquid asset ratio (savings drain threatens liquidity floor).

Rule 3: Regulatory Liquid Asset Ratio Breach
  Trigger: regulatory_liquid_ratio_pct < 10.0 (SASRA hard floor)
  Action: Treasury / Finance team must rebalance liquid assets within 2 working days.
  Constraint: SASRA regulatory liquid asset ratio (hard constraint).

Rule 4: Loan-to-Deposit Ratio Breach
  Trigger: loan_to_deposit_ratio_pct > 80.0 (SASRA ceiling)
  Action: Credit team must pause new disbursements and notify Head of Credit same day.
  Constraint: SASRA loan-to-deposit ratio (hard constraint).

Rule 5: PAR30 Escalation
  Trigger: par30_breach_flag = 1 AND default_propensity_score >= 60
  Action: Collections team escalates to legal within 5 working days.
  Constraint: Provision coverage ratio (board soft constraint >= 60% of PAR30 balance).
"""

import pandas as pd
import numpy as np

# [ASSUMPTION] Relationship Officers can handle 80 member contacts per week.
# Adjust to actual team size before live deployment.
WEEKLY_INTERVENTION_CAPACITY = 80

print("=== STIMA SACCO RULE ENGINE ===")

scored   = pd.read_csv('member_scored.csv', parse_dates=['snapshot_date'])
contrib  = pd.read_csv('monthly_contributions.csv', parse_dates=['snapshot_date'])
members  = pd.read_csv('members.csv')
loans    = pd.read_csv('loan_book.csv')

contrib = contrib.merge(members[['member_id', 'tier']], on='member_id', how='left', suffixes=('', '_mbr'))
if 'tier_mbr' in contrib.columns:
    contrib['tier'] = contrib['tier'].fillna(contrib['tier_mbr'])
    contrib.drop(columns=['tier_mbr'], errors='ignore', inplace=True)

current_period  = contrib['snapshot_date'].max()
current_contrib = contrib[contrib['snapshot_date'] == current_period].copy()
current_scored  = scored[scored['snapshot_date'] == scored['snapshot_date'].max()].copy()

print(f"Evaluating rules for period: {current_period.date()}")
print(f"Members evaluated: {len(current_contrib)}")


# ============================================================
# RULE FUNCTIONS
# ============================================================

def contribution_gap_alert(df):
    """
    Rule 1: Contribution Gap Alert
    Trigger: days_since_last_contribution >= tier threshold
    Source: Sequencing constraint - must intervene before PAR30 is confirmed.
    Action: Relationship Officer contacts member within 5 working days.
    """
    tier_thresh = {'Premium': 30, 'Standard': 45, 'Basic': 60}
    thresholds  = df['tier'].map(tier_thresh).fillna(45)
    return df['days_since_last_contribution'].fillna(0) >= thresholds


def withdrawal_surge_alert(df):
    """
    Rule 2: Withdrawal Surge Alert
    Trigger: withdrawal_surge_index >= 2.0
    Source: Liquid asset ratio constraint - savings drain threatens SASRA floor.
    Action: Branch Manager initiates financial wellness call within 3 working days.
    """
    return df['withdrawal_surge_index'] >= 2.0


def liquidity_ratio_breach(df):
    """
    Rule 3: Regulatory Liquid Asset Ratio Breach
    Trigger: regulatory_liquid_ratio_pct < 10.0 (SASRA hard floor)
    Source: SASRA regulatory requirement.
    Action: Treasury team rebalances liquid assets within 2 working days.
    """
    return df['regulatory_liquid_ratio_pct'] < 10.0


def loan_to_deposit_breach(df):
    """
    Rule 4: Loan-to-Deposit Ratio Breach
    Trigger: loan_to_deposit_ratio_pct > 80.0 (SASRA ceiling)
    Source: SASRA regulatory requirement.
    Action: Credit team pauses new disbursements same day.
    """
    return df['loan_to_deposit_ratio_pct'] > 80.0


def par30_escalation(df_contrib, df_scored):
    """
    Rule 5: PAR30 Escalation
    Trigger: par30_breach_flag = 1 AND propensity score >= 60
    Source: Provision coverage soft constraint.
    Action: Collections team escalates to legal within 5 working days.
    """
    merged = df_contrib.merge(
        df_scored[['member_id', 'default_propensity_score', 'par30_breach_flag']],
        on='member_id', how='left',
        suffixes=('', '_scored')
    )
    par_col   = 'par30_breach_flag_scored' if 'par30_breach_flag_scored' in merged.columns else 'par30_breach_flag'
    score_col = 'default_propensity_score'
    return (merged[par_col].fillna(0) == 1) & \
           (merged[score_col].fillna(0) >= 60)


# Evaluate
current_contrib['rule_contribution_gap']    = contribution_gap_alert(current_contrib)
current_contrib['rule_withdrawal_surge']    = withdrawal_surge_alert(current_contrib)
current_contrib['rule_liquidity_breach']    = liquidity_ratio_breach(current_contrib)
current_contrib['rule_ltd_breach']          = loan_to_deposit_breach(current_contrib)
current_contrib['rule_par30_escalation']    = par30_escalation(current_contrib, current_scored)

RULE_LABELS = {
    'rule_contribution_gap':  'Contribution Gap Alert',
    'rule_withdrawal_surge':  'Withdrawal Surge Alert',
    'rule_liquidity_breach':  'Liquidity Ratio Breach',
    'rule_ltd_breach':        'LTD Ratio Breach',
    'rule_par30_escalation':  'PAR30 Escalation',
}
rule_cols = list(RULE_LABELS.keys())

def get_fired(row):
    fired = [RULE_LABELS[c] for c in rule_cols if row.get(c, False)]
    return ', '.join(fired) if fired else ''

current_contrib['rule_names_fired']  = current_contrib.apply(get_fired, axis=1)
current_contrib['rules_fired_count'] = current_contrib[rule_cols].sum(axis=1)

# Merge with scored output
output = current_contrib[[
    'member_id', 'tier', 'rule_names_fired', 'rules_fired_count',
    'days_since_last_contribution', 'withdrawal_surge_index',
    'regulatory_liquid_ratio_pct', 'loan_to_deposit_ratio_pct',
    'monthly_contribution_kes', 'last_actioned_date'
]].copy()

output = output.merge(
    current_scored[['member_id', 'default_propensity_score', 'risk_band',
                    'constraint_override', 'constraint_override_reason',
                    'loan_outstanding_kes', 'par30_breach_flag']],
    on='member_id', how='left'
)

output['compliance_status'] = output.apply(
    lambda r: 'BREACH' if (
        r['regulatory_liquid_ratio_pct'] < 10.0 or
        r['loan_to_deposit_ratio_pct'] > 80.0
    ) else 'COMPLIANT', axis=1
)

# Priority ranking
def assign_priority(row):
    if row['compliance_status'] == 'BREACH':
        return 1
    if row['risk_band'] == 'HIGH' and row['rules_fired_count'] > 0 and not row['constraint_override']:
        return 2
    if row['risk_band'] == 'HIGH' and row['rules_fired_count'] == 0 and not row['constraint_override']:
        return 3
    if row['risk_band'] == 'MEDIUM' and row['rules_fired_count'] > 0 and not row['constraint_override']:
        return 4
    if row['risk_band'] == 'MEDIUM' and row['rules_fired_count'] == 0:
        return 5
    if row['constraint_override']:
        return 6
    return 7

output['priority_rank'] = output.apply(assign_priority, axis=1)
output = output.sort_values(
    ['priority_rank', 'default_propensity_score'],
    ascending=[True, False]
).reset_index(drop=True)

def get_action(row):
    if row['compliance_status'] == 'BREACH':
        if row['regulatory_liquid_ratio_pct'] < 10.0:
            return f"Treasury must rebalance liquid assets above 10% within 2 working days. Current: {row['regulatory_liquid_ratio_pct']:.1f}%."
        return f"Credit team must pause new disbursements immediately. LTD ratio: {row['loan_to_deposit_ratio_pct']:.1f}%."
    fired = row['rule_names_fired']
    if 'PAR30 Escalation' in fired:
        return f"Collections team escalates member {row['member_id']} to legal within 5 working days."
    if 'Contribution Gap' in fired:
        return f"Relationship Officer contacts {row['member_id']} within 5 working days (gap: {row['days_since_last_contribution']:.0f} days)."
    if 'Withdrawal Surge' in fired:
        return f"Branch Manager initiates financial wellness call for {row['member_id']} within 3 working days (index: {row['withdrawal_surge_index']:.1f})."
    if row['risk_band'] == 'HIGH':
        return f"Relationship Officer reviews {row['member_id']} proactively. Score: {row['default_propensity_score']:.0f}/100."
    return "Monitor at next scheduled monthly review."

output['recommended_action'] = output.apply(get_action, axis=1)

output['constraint_compliant_action'] = output.apply(
    lambda r: (
        "Refer to Credit Committee before any restructure or top-up. "
        "Single-borrower concentration limit under review."
    ) if r['constraint_override'] else "", axis=1
)

output['time_window_for_response'] = output['priority_rank'].map({
    1: 'Same day / 2 working days',
    2: '3 working days',
    3: '5 working days',
    4: '5 working days',
    5: '10 working days',
    6: '5 working days (post Credit Committee)',
    7: 'Next monthly review'
})

def get_trigger(row):
    if row['compliance_status'] == 'BREACH':
        return ('regulatory_liquid_ratio_pct' if row['regulatory_liquid_ratio_pct'] < 10 else 'loan_to_deposit_ratio_pct',
                row['regulatory_liquid_ratio_pct'] if row['regulatory_liquid_ratio_pct'] < 10 else row['loan_to_deposit_ratio_pct'])
    if 'Contribution Gap' in row['rule_names_fired']:
        return 'days_since_last_contribution', row['days_since_last_contribution']
    if 'Withdrawal Surge' in row['rule_names_fired']:
        return 'withdrawal_surge_index', row['withdrawal_surge_index']
    return 'default_propensity_score', row['default_propensity_score']

output[['trigger_metric', 'trigger_value']] = output.apply(
    lambda r: pd.Series(get_trigger(r)), axis=1
)

tier_thresh_str = {'Premium': '30 days / WSI 2.0', 'Standard': '45 days / WSI 2.0', 'Basic': '60 days / WSI 2.0'}
output['threshold'] = output['tier'].map(tier_thresh_str).fillna('45 days / WSI 2.0')

output['excluded_reason'] = ''
if len(output) > WEEKLY_INTERVENTION_CAPACITY:
    output.loc[output.index[WEEKLY_INTERVENTION_CAPACITY:], 'excluded_reason'] = 'capacity_limit'

final_cols = [
    'member_id', 'tier', 'rule_names_fired', 'trigger_metric', 'trigger_value',
    'threshold', 'default_propensity_score', 'risk_band', 'priority_rank',
    'constraint_override', 'constraint_override_reason', 'recommended_action',
    'constraint_compliant_action', 'time_window_for_response', 'excluded_reason',
    'last_actioned_date', 'days_since_last_contribution', 'withdrawal_surge_index',
    'loan_outstanding_kes', 'par30_breach_flag', 'compliance_status',
    'regulatory_liquid_ratio_pct', 'loan_to_deposit_ratio_pct'
]
output[final_cols].to_csv('rule_engine_output.csv', index=False)
print("\nSaved: rule_engine_output.csv")

re_audit = {
    'rule_engine.total_members_evaluated':     len(output),
    'rule_engine.members_with_rules_fired':    int((output['rules_fired_count'] > 0).sum()),
    'rule_engine.members_in_action_list':      min(WEEKLY_INTERVENTION_CAPACITY, len(output)),
    'rule_engine.members_excluded_capacity':   int((output['excluded_reason'] == 'capacity_limit').sum()),
    'rule_engine.members_constraint_override': int(output['constraint_override'].fillna(False).sum()),
    'rule_engine.members_rank_1':              int((output['priority_rank'] == 1).sum()),
    'rule_engine.members_rank_2':              int((output['priority_rank'] == 2).sum()),
    'rule_engine.members_rank_3':              int((output['priority_rank'] == 3).sum()),
}

print("\n===== RULE ENGINE AUDIT =====")
for k, v in re_audit.items():
    print(f"  {k}: {v}")

print("\n===== TOP 5 PRIORITY ACTIONS =====")
for _, row in output.head(5).iterrows():
    print(f"\n  [{row['priority_rank']}] {row['member_id']} ({row['tier']}) | {row['risk_band']} | Score: {row['default_propensity_score']:.0f}")
    print(f"      Rules: {row['rule_names_fired'] or 'None'}")
    print(f"      Action: {row['recommended_action']}")
    print(f"      Window: {row['time_window_for_response']}")

print("\nrule_engine.py complete.")
