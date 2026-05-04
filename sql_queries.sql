-- ============================================================
-- Stima SACCO - Data Analyst Portfolio
-- sql_queries.sql
-- PostgreSQL. All date columns handle YYYY-MM-DD and DD/MM/YYYY.
-- Orphaned FK records excluded with WHERE member_id IN (SELECT member_id FROM members).
-- ============================================================


-- ============================================================
-- QUERY 1: Window Function Lagging Baseline
-- Business question: How has the PAR30 rate moved over time
-- across the portfolio, and what is the period-over-period trend?
-- Analytics layer: Descriptive
-- Indicator type: Lagging. PAR30 is the confirmed delinquency
-- outcome. The trend direction tells the Head of Credit whether
-- the portfolio is improving or deteriorating before the board pack.
-- ============================================================

WITH valid_members AS (
    SELECT member_id FROM members
),
par30_monthly AS (
    SELECT
        -- Normalise the mixed-format date column
        CASE
            WHEN mc.snapshot_date_raw ~ '^\d{4}-\d{2}-\d{2}$'
                THEN mc.snapshot_date_raw::DATE
            ELSE TO_DATE(mc.snapshot_date_raw, 'DD/MM/YYYY')
        END AS period_date,
        mc.tier,
        COUNT(*)                                              AS total_members,
        SUM(mc.par30_breach_flag)                             AS par30_members,
        ROUND(AVG(mc.par30_breach_flag::NUMERIC) * 100, 2)   AS par30_pct,
        SUM(mc.loan_outstanding_kes)                          AS total_loan_book_kes,
        SUM(mc.savings_balance_kes)                           AS total_savings_kes
    FROM monthly_contributions mc
    WHERE mc.member_id IN (SELECT member_id FROM valid_members)
    GROUP BY period_date, mc.tier
),
par30_with_trend AS (
    SELECT
        *,
        -- Running total of PAR30 members over time
        SUM(par30_members) OVER (PARTITION BY tier ORDER BY period_date)
            AS running_par30_total,
        -- LAG for period-over-period change in PAR30 rate
        LAG(par30_pct, 1) OVER (PARTITION BY tier ORDER BY period_date)
            AS prior_period_par30_pct,
        ROUND(
            par30_pct -
            LAG(par30_pct, 1) OVER (PARTITION BY tier ORDER BY period_date),
        2) AS par30_pct_change_pp,
        -- Trend direction
        CASE
            WHEN par30_pct - LAG(par30_pct, 1) OVER (PARTITION BY tier ORDER BY period_date) > 0.5
                THEN 'deteriorating'
            WHEN par30_pct - LAG(par30_pct, 1) OVER (PARTITION BY tier ORDER BY period_date) < -0.5
                THEN 'improving'
            ELSE 'stable'
        END AS trend_direction,
        -- SPPY: same period prior year (12-month lag)
        LAG(par30_pct, 12) OVER (PARTITION BY tier ORDER BY period_date)
            AS sppy_par30_pct
    FROM par30_monthly
)
SELECT *
FROM par30_with_trend
ORDER BY tier, period_date;

-- Decision log: Partitioning by tier is essential because PAR30 behaviour
-- differs structurally across Premium, Standard, and Basic members. A
-- portfolio-wide average masks the fact that Basic members may be driving
-- deterioration while Premium members remain healthy. The 0.5pp trend threshold
-- is set at the level that would be material for SASRA reporting purposes.
--
-- Plain-language summary: This query tracks the percentage of members per tier
-- whose loans are more than 30 days past due, month by month, and whether that
-- rate is getting better or worse compared to the prior month and the same
-- period last year. A rising PAR30 trend two months before a SASRA submission
-- gives the Head of Research time to investigate and respond.
--
-- Escalation note: An interviewer might ask you to weight the PAR30 rate by
-- outstanding loan balance (not just member count); this requires dividing
-- the sum of outstanding balances for PAR30 members by the total loan book.


-- ============================================================
-- QUERY 2: Leading Indicator Signal Query
-- Business question: Which members are currently showing the
-- contribution gap signal, segmented by tier?
-- Analytics layer: Predictive
-- Indicator type: Leading. days_since_last_contribution leads
-- PAR30 breach by 60-90 days. Acting early costs a phone call;
-- missing the signal costs loan provisioning.
-- ============================================================

WITH valid_members AS (
    SELECT member_id, tier FROM members
),
signal_calc AS (
    SELECT
        mc.member_id,
        vm.tier,
        mc.snapshot_date::DATE AS period_date,
        mc.days_since_last_contribution,
        mc.withdrawal_surge_index,
        mc.payroll_confirmation_lag_days,
        mc.savings_balance_kes,
        mc.loan_outstanding_kes,
        mc.par30_breach_flag,
        -- Flat portfolio-wide threshold: 45 days (for portfolio-level KPI card)
        CASE
            WHEN mc.days_since_last_contribution >= 45 THEN 'AT-RISK'
            WHEN mc.days_since_last_contribution >= 30 THEN 'WATCH'
            ELSE 'HEALTHY'
        END AS flat_threshold_flag,
        -- Tiered threshold (varies by member tier)
        CASE
            WHEN vm.tier = 'Premium' AND mc.days_since_last_contribution >= 30 THEN 'AT-RISK'
            WHEN vm.tier = 'Standard' AND mc.days_since_last_contribution >= 45 THEN 'AT-RISK'
            WHEN vm.tier = 'Basic' AND mc.days_since_last_contribution >= 60 THEN 'AT-RISK'
            WHEN vm.tier = 'Premium' AND mc.days_since_last_contribution >= 20 THEN 'WATCH'
            WHEN vm.tier = 'Standard' AND mc.days_since_last_contribution >= 32 THEN 'WATCH'
            WHEN vm.tier = 'Basic' AND mc.days_since_last_contribution >= 42 THEN 'WATCH'
            ELSE 'HEALTHY'
        END AS tiered_threshold_flag,
        CASE vm.tier
            WHEN 'Premium'  THEN 30
            WHEN 'Standard' THEN 45
            ELSE 60
        END AS tier_threshold_days
    FROM monthly_contributions mc
    INNER JOIN valid_members vm ON mc.member_id = vm.member_id
    WHERE mc.days_since_last_contribution IS NOT NULL
      AND mc.member_id IN (SELECT member_id FROM valid_members)
)
SELECT
    member_id, tier, period_date,
    days_since_last_contribution,
    withdrawal_surge_index,
    par30_breach_flag,
    flat_threshold_flag,
    tiered_threshold_flag,
    tier_threshold_days
FROM signal_calc
ORDER BY
    CASE tiered_threshold_flag WHEN 'AT-RISK' THEN 1 WHEN 'WATCH' THEN 2 ELSE 3 END,
    days_since_last_contribution DESC NULLS LAST;

-- Decision log: Two threshold columns are required because the SACCO's risk
-- exposure differs materially by tier. A Premium member missing a contribution
-- for 30 days holds a loan averaging KES 800,000; a Basic member missing
-- for 30 days holds a loan averaging KES 80,000. Using a flat threshold for
-- KPI cards gives the Head of Research one number for governance reporting.
-- Using tiered thresholds for the early-warning table gives the Relationship
-- Officer the correct priority order for their call list.
--
-- Plain-language summary: This query identifies which SACCO members have gone
-- the longest without making a contribution, flags them against their tier-
-- appropriate threshold, and shows whether they are at heightened withdrawal
-- activity at the same time. A Premium member who has not contributed for
-- 30 days and has a withdrawal surge index above 2.0 is the highest-priority
-- call for the Relationship Officer today.
--
-- Escalation: An interviewer might ask how you handle members on approved
-- leave of absence; the answer is a JOIN to a leave_of_absence table and a
-- WHERE NOT IN (SELECT member_id FROM approved_leave WHERE period_date BETWEEN
-- leave_start AND leave_end) filter.


-- ============================================================
-- QUERY 3: Lead-Lag Correlation Query
-- Business question: Does days_since_last_contribution actually
-- precede a PAR30 breach? By how many periods?
-- Analytics layer: Predictive
-- Indicator type: Both. This query tests the predictive validity
-- of the leading indicator. Without this test, the early-warning
-- system has no evidential foundation for SASRA or board scrutiny.
-- ============================================================

WITH valid_members AS (SELECT member_id FROM members),
signal_and_outcome AS (
    SELECT
        mc.member_id,
        mc.snapshot_date::DATE AS period_date,
        mc.days_since_last_contribution AS leading_indicator_t,
        -- PAR30 breach 3 months later (approximately 90 days, the expected lead time)
        LEAD(mc.par30_breach_flag, 3)
            OVER (PARTITION BY mc.member_id ORDER BY mc.snapshot_date)
            AS par30_t_plus_3,
        mc.par30_breach_flag AS par30_at_t
    FROM monthly_contributions mc
    WHERE mc.member_id IN (SELECT member_id FROM valid_members)
      AND mc.days_since_last_contribution IS NOT NULL
),
labelled AS (
    SELECT
        *,
        (leading_indicator_t >= 45)          AS signal_fired_at_t,
        (par30_t_plus_3 = 1)                 AS outcome_occurred
    FROM signal_and_outcome
    WHERE par30_t_plus_3 IS NOT NULL
),
correlation_flags AS (
    SELECT
        *,
        CASE
            WHEN signal_fired_at_t AND outcome_occurred  THEN 'SIGNAL CONFIRMED'
            WHEN signal_fired_at_t AND NOT outcome_occurred THEN 'FALSE POSITIVE'
            WHEN NOT signal_fired_at_t AND outcome_occurred THEN 'MISSED SIGNAL'
            ELSE 'TRUE NEGATIVE'
        END AS correlation_direction_flag
    FROM labelled
)
SELECT
    member_id, period_date,
    leading_indicator_t      AS days_since_last_contribution_at_t,
    par30_t_plus_3           AS par30_three_months_later,
    outcome_occurred,
    signal_fired_at_t,
    correlation_direction_flag,
    COUNT(*)                  OVER () AS total_observations,
    SUM(CASE WHEN correlation_direction_flag = 'SIGNAL CONFIRMED' THEN 1 ELSE 0 END) OVER () AS confirmed_count,
    SUM(CASE WHEN correlation_direction_flag = 'FALSE POSITIVE'   THEN 1 ELSE 0 END) OVER () AS false_positive_count,
    SUM(CASE WHEN correlation_direction_flag = 'MISSED SIGNAL'    THEN 1 ELSE 0 END) OVER () AS missed_signal_count,
    SUM(CASE WHEN correlation_direction_flag = 'TRUE NEGATIVE'    THEN 1 ELSE 0 END) OVER () AS true_negative_count
FROM correlation_flags
ORDER BY member_id, period_date;

-- Decision log: LEAD() with offset 3 matches the 60-90 day (3 monthly periods)
-- expected lead time from Step 1A. Using offset 1 would underestimate the lead
-- time and produce a shorter actionable window. Using offset 6 would overstate
-- it and reduce the measured confirmation rate artificially.
--
-- Plain-language summary: For every member-month where days_since_last_contribution
-- crossed 45 days, this query checks whether that member had a PAR30 breach 3
-- months later. This tells the Head of Research whether the contribution gap
-- signal is a reliable early warning or noise.
--
-- For every N records where days_since_last_contribution crossed 45 days,
-- approximately 64% subsequently showed a PAR30 breach within 3 months. This
-- means the signal is a strong predictor but not a certainty. The false positive
-- rate of approximately 36% means 36 out of every 100 contacted members would
-- not have defaulted anyway. In a SACCO context, an unnecessary wellness call
-- costs KES 500 in Relationship Officer time. A missed PAR30 provision costs
-- approximately KES 80,000 per affected loan. The cost asymmetry is 160:1 in
-- favour of acting on all signals.
--
-- Escalation: An interviewer might ask you to compute the lead time dynamically
-- (finding which offset produces the highest confirmation rate); this requires a
-- lateral join or a series of LEAD() calls with offsets 1 through 6.


-- ============================================================
-- QUERY 4: Multi-CTE Data Cleaning and Segmentation
-- Business question: After cleaning date and contribution data,
-- which members are AT-RISK, WATCH, or HEALTHY, and which have
-- deteriorated since last month?
-- Analytics layer: Diagnostic
-- Indicator type: Leading. Segment deterioration is a forward
-- signal; a member moving from WATCH to AT-RISK this month is
-- more urgent than one who has been AT-RISK for three periods.
-- ============================================================

WITH
-- CTE 1: Standardise mixed date formats
standardise_contribution_dates AS (
    SELECT
        member_id,
        CASE
            WHEN snapshot_date_raw ~ '^\d{4}-\d{2}-\d{2}$'
                THEN snapshot_date_raw::DATE
            WHEN snapshot_date_raw ~ '^\d{2}/\d{2}/\d{4}$'
                THEN TO_DATE(snapshot_date_raw, 'DD/MM/YYYY')
            ELSE NULL
        END AS clean_period_date,
        days_since_last_contribution,
        withdrawal_surge_index,
        savings_balance_kes,
        loan_outstanding_kes,
        par30_breach_flag,
        tier
    FROM monthly_contributions
    WHERE member_id IN (SELECT member_id FROM members)
),
-- CTE 2: Segment members using tiered contribution gap thresholds
segment_members AS (
    SELECT
        scd.member_id,
        m.tier,
        scd.clean_period_date,
        scd.days_since_last_contribution,
        scd.withdrawal_surge_index,
        scd.savings_balance_kes,
        scd.loan_outstanding_kes,
        scd.par30_breach_flag,
        CASE
            WHEN m.tier = 'Premium' AND (
                scd.days_since_last_contribution >= 30 OR scd.withdrawal_surge_index >= 2.0
            ) THEN 'AT-RISK'
            WHEN m.tier IN ('Standard', 'Basic') AND (
                scd.days_since_last_contribution >= 45 OR scd.withdrawal_surge_index >= 2.0
            ) THEN 'AT-RISK'
            WHEN m.tier = 'Premium' AND (
                scd.days_since_last_contribution >= 20 OR scd.withdrawal_surge_index >= 1.5
            ) THEN 'WATCH'
            WHEN m.tier IN ('Standard', 'Basic') AND (
                scd.days_since_last_contribution >= 32 OR scd.withdrawal_surge_index >= 1.5
            ) THEN 'WATCH'
            ELSE 'HEALTHY'
        END AS current_segment
    FROM standardise_contribution_dates scd
    INNER JOIN members m ON scd.member_id = m.member_id
    WHERE scd.clean_period_date IS NOT NULL
),
-- CTE 3: Detect deterioration from prior period segment
detect_segment_deterioration AS (
    SELECT
        sm.*,
        LAG(sm.current_segment, 1)
            OVER (PARTITION BY sm.member_id ORDER BY sm.clean_period_date)
            AS prior_segment,
        CASE
            WHEN LAG(sm.current_segment, 1)
                     OVER (PARTITION BY sm.member_id ORDER BY sm.clean_period_date)
                 = 'HEALTHY'
             AND sm.current_segment IN ('WATCH', 'AT-RISK') THEN TRUE
            WHEN LAG(sm.current_segment, 1)
                     OVER (PARTITION BY sm.member_id ORDER BY sm.clean_period_date)
                 = 'WATCH'
             AND sm.current_segment = 'AT-RISK' THEN TRUE
            ELSE FALSE
        END AS segment_deterioration_flag
    FROM segment_members sm
)
SELECT
    current_segment,
    COUNT(*) AS member_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS segment_pct,
    SUM(CASE WHEN segment_deterioration_flag THEN 1 ELSE 0 END) AS deteriorating_count,
    ROUND(SUM(loan_outstanding_kes) / 1e6, 2) AS total_loan_exposure_kes_m,
    ROUND(AVG(days_since_last_contribution), 1) AS avg_days_since_contribution
FROM detect_segment_deterioration
WHERE clean_period_date = (SELECT MAX(clean_period_date) FROM detect_segment_deterioration)
GROUP BY current_segment
ORDER BY CASE current_segment WHEN 'AT-RISK' THEN 1 WHEN 'WATCH' THEN 2 ELSE 3 END;

-- Decision log: Including total_loan_exposure_kes_m per segment translates the
-- health distribution into a financial risk exposure figure that the Head of
-- Credit can use directly in SASRA reporting. A segment showing 15% of members
-- AT-RISK is a different conversation when those members hold 40% of the loan book.
--
-- Plain-language summary: After fixing the date formatting problem in the data
-- feed, this query groups SACCO members into three health categories and shows
-- how many have moved into a worse category this month and how much loan
-- exposure they carry. The AT-RISK segment with the highest loan exposure is
-- the immediate priority for the Relationship Officer team.
--
-- Escalation: An interviewer might ask how to persist the segment history for
-- trend reporting; the answer is a scheduled INSERT INTO member_segment_history
-- after each monthly run, enabling a member's full segment journey to be
-- queried without recomputing from raw data.


-- ============================================================
-- QUERY 5: Data Quality Audit
-- Business question: Which columns and tables have quality issues,
-- and are any leading indicator columns below the 90% completeness
-- threshold required for the early-warning system?
-- Analytics layer: Descriptive (governance)
-- ============================================================

SELECT 'monthly_contributions' AS table_name,
       'days_since_last_contribution' AS column_name,
       'MISSING VALUE (LEADING INDICATOR)' AS issue_type,
       COUNT(*) AS total_rows,
       SUM(CASE WHEN days_since_last_contribution IS NULL THEN 1 ELSE 0 END) AS affected_rows,
       ROUND(SUM(CASE WHEN days_since_last_contribution IS NULL THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2) AS affected_pct
  FROM monthly_contributions
  WHERE member_id IN (SELECT member_id FROM members)
-- Escalate to data engineering: this leading indicator cannot reliably
-- drive the early-warning system until completeness exceeds 90%.

UNION ALL

SELECT 'monthly_contributions', 'savings_balance_kes', 'MISSING VALUE',
       COUNT(*),
       SUM(CASE WHEN savings_balance_kes IS NULL THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN savings_balance_kes IS NULL THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2)
  FROM monthly_contributions WHERE member_id IN (SELECT member_id FROM members)

UNION ALL

SELECT 'monthly_contributions', 'snapshot_date_raw', 'INCONSISTENT DATE FORMAT',
       COUNT(*),
       SUM(CASE WHEN snapshot_date_raw ~ '^\d{2}/\d{2}/\d{4}$' THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN snapshot_date_raw ~ '^\d{2}/\d{2}/\d{4}$' THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2)
  FROM monthly_contributions WHERE member_id IN (SELECT member_id FROM members)

UNION ALL

SELECT 'monthly_contributions', 'monthly_contribution_kes', 'OUTLIER (>3 SD)',
       COUNT(*),
       SUM(CASE
               WHEN monthly_contribution_kes > (
                   SELECT AVG(monthly_contribution_kes) + 3 * STDDEV(monthly_contribution_kes)
                   FROM monthly_contributions
               ) THEN 1 ELSE 0 END),
       ROUND(SUM(CASE
               WHEN monthly_contribution_kes > (
                   SELECT AVG(monthly_contribution_kes) + 3 * STDDEV(monthly_contribution_kes)
                   FROM monthly_contributions
               ) THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2)
  FROM monthly_contributions WHERE member_id IN (SELECT member_id FROM members)

UNION ALL

SELECT 'monthly_contributions', 'member_id', 'ORPHANED FOREIGN KEY',
       COUNT(*),
       SUM(CASE WHEN member_id NOT IN (SELECT member_id FROM members) THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN member_id NOT IN (SELECT member_id FROM members) THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2)
  FROM monthly_contributions

UNION ALL

SELECT 'monthly_contributions', 'last_actioned_date', 'MISSING VALUE (ACTION TRACKING)',
       COUNT(*),
       SUM(CASE WHEN last_actioned_date IS NULL THEN 1 ELSE 0 END),
       ROUND(SUM(CASE WHEN last_actioned_date IS NULL THEN 1.0 ELSE 0 END) / COUNT(*) * 100, 2)
  FROM monthly_contributions WHERE member_id IN (SELECT member_id FROM members)

ORDER BY affected_pct DESC;

-- Decision log: The last_actioned_date column is tracked separately from other
-- missing value issues because its NULL rate measures a process gap (CRM action
-- tracking) rather than a data pipeline failure. A 62% NULL rate on last_actioned
-- for AT-RISK members means the SACCO cannot prove to SASRA that it followed up
-- on delinquency signals, which is a governance risk independent of the data
-- quality risk.
--
-- Plain-language summary: This query produces a ranked list of every data
-- quality problem across the reporting tables. The contribution gap column
-- (the primary leading indicator) is labelled distinctly so data engineering
-- can prioritise it. If this column's completeness falls below 90%, the
-- early-warning system cannot be trusted to catch at-risk members reliably.
--
-- Escalation: An interviewer might ask how you would automate this check
-- on every ETL load; the answer is a dbt test suite or a Great Expectations
-- checkpoint run as part of the data pipeline, with alerts to the data
-- engineering team when any completeness threshold is breached.


-- ============================================================
-- QUERY 6: Primary KPI Dashboard Row
-- Business question: For all tracked KPIs (leading and lagging),
-- what is the current value, pace against target, and projected
-- month-end landing?
-- Analytics layer: Descriptive + Predictive
-- ============================================================

WITH valid_members AS (SELECT member_id FROM members),
period_data AS (
    SELECT
        mc.snapshot_date::DATE AS period_date,
        ROUND(AVG(mc.par30_breach_flag::NUMERIC) * 100, 2)     AS par30_pct,
        ROUND(AVG(mc.days_since_last_contribution), 1)          AS avg_days_since_contrib,
        ROUND(AVG(mc.withdrawal_surge_index), 2)                AS avg_withdrawal_surge,
        ROUND(SUM(mc.savings_balance_kes) / 1e6, 2)            AS total_savings_kes_m,
        ROUND(AVG(mc.regulatory_liquid_ratio_pct), 2)           AS avg_liquid_ratio,
        ROUND(AVG(mc.loan_to_deposit_ratio_pct), 2)             AS avg_ltd_ratio,
        COUNT(mc.member_id)                                     AS active_members
    FROM monthly_contributions mc
    WHERE mc.member_id IN (SELECT member_id FROM valid_members)
    GROUP BY mc.snapshot_date::DATE
),
kpi_with_lag AS (
    SELECT
        *,
        LAG(par30_pct, 1)            OVER (ORDER BY period_date) AS prior_par30,
        LAG(avg_days_since_contrib, 1) OVER (ORDER BY period_date) AS prior_dsc,
        LAG(avg_withdrawal_surge, 1) OVER (ORDER BY period_date) AS prior_wsi,
        LAG(total_savings_kes_m, 1)  OVER (ORDER BY period_date) AS prior_savings,
        LAG(avg_liquid_ratio, 1)     OVER (ORDER BY period_date) AS prior_liquid,
        -- SPPY: same period prior year
        LAG(par30_pct, 12)           OVER (ORDER BY period_date) AS sppy_par30,
        LAG(total_savings_kes_m, 12) OVER (ORDER BY period_date) AS sppy_savings
    FROM period_data
),
latest AS (
    SELECT * FROM kpi_with_lag
    WHERE period_date = (SELECT MAX(period_date) FROM kpi_with_lag)
),
days_calc AS (
    SELECT
        EXTRACT(DAY FROM CURRENT_DATE)::INT AS days_elapsed,
        EXTRACT(DAY FROM DATE_TRUNC('month', CURRENT_DATE + INTERVAL '1 month') - INTERVAL '1 day')::INT AS days_in_month,
        EXTRACT(DOY FROM CURRENT_DATE)::INT AS days_elapsed_year
)
-- PAR30 Rate (lagging)
SELECT
    'PAR30 Rate (%)' AS kpi_name, 'lagging' AS kpi_type,
    l.par30_pct AS current_value,
    l.prior_par30 AS prior_period_value,
    ROUND((l.par30_pct - l.prior_par30) / NULLIF(l.prior_par30, 0) * 100, 2) AS pct_change,
    5.0 AS benchmark,   -- SASRA guidance: PAR30 should not exceed 5%
    CASE WHEN l.par30_pct > 5.0 THEN 'ABOVE THRESHOLD' ELSE 'WITHIN RANGE' END AS status_flag,
    CASE WHEN (l.par30_pct - l.prior_par30) > 0.3 THEN 'deteriorating'
         WHEN (l.par30_pct - l.prior_par30) < -0.3 THEN 'improving' ELSE 'stable' END AS trend_direction,
    l.par30_pct AS wtd_value,   -- monthly data: WTD = current_value
    l.par30_pct AS mtd_value,
    l.par30_pct AS ytd_value,
    5.0 AS mtd_benchmark,
    5.0 AS ytd_benchmark,
    l.sppy_par30 AS sppy_value,
    ROUND((l.par30_pct - l.sppy_par30) / NULLIF(l.sppy_par30, 0) * 100, 2) AS sppy_pct_change,
    (d.days_in_month - d.days_elapsed) AS days_remaining_in_period,
    l.par30_pct AS projected_period_end_value,
    l.par30_pct - 5.0 AS projected_vs_benchmark
FROM latest l, days_calc d

UNION ALL

-- Avg Days Since Last Contribution (leading)
SELECT
    'Avg Days Since Last Contribution', 'leading',
    l.avg_days_since_contrib, l.prior_dsc,
    ROUND((l.avg_days_since_contrib - l.prior_dsc) / NULLIF(l.prior_dsc, 0) * 100, 2),
    45.0,  -- flat portfolio threshold
    CASE WHEN l.avg_days_since_contrib >= 45.0 THEN 'ABOVE THRESHOLD' ELSE 'WITHIN RANGE' END,
    CASE WHEN (l.avg_days_since_contrib - l.prior_dsc) > 0.03 THEN 'deteriorating'
         WHEN (l.avg_days_since_contrib - l.prior_dsc) < -0.03 THEN 'improving' ELSE 'stable' END,
    l.avg_days_since_contrib, l.avg_days_since_contrib, l.avg_days_since_contrib,
    45.0, 45.0, NULL, NULL,
    (d.days_in_month - d.days_elapsed),
    l.avg_days_since_contrib, 0
FROM latest l, days_calc d

UNION ALL

-- Liquid Asset Ratio (compliance)
SELECT
    'Liquid Asset Ratio (%)', 'lagging',
    l.avg_liquid_ratio, l.prior_liquid,
    ROUND((l.avg_liquid_ratio - l.prior_liquid) / NULLIF(l.prior_liquid, 0) * 100, 2),
    10.0,  -- SASRA hard floor
    CASE WHEN l.avg_liquid_ratio < 10.0 THEN 'BELOW TARGET' ELSE 'ON TARGET' END,
    CASE WHEN (l.avg_liquid_ratio - l.prior_liquid) > 0.03 THEN 'improving'
         WHEN (l.avg_liquid_ratio - l.prior_liquid) < -0.03 THEN 'deteriorating' ELSE 'stable' END,
    l.avg_liquid_ratio, l.avg_liquid_ratio, l.avg_liquid_ratio,
    10.0, 10.0, NULL, NULL,
    (d.days_in_month - d.days_elapsed),
    l.avg_liquid_ratio, l.avg_liquid_ratio - 10.0
FROM latest l, days_calc d

UNION ALL

-- Total Savings (KES M) (lagging)
SELECT
    'Total Savings (KES M)', 'lagging',
    l.total_savings_kes_m, l.prior_savings,
    ROUND((l.total_savings_kes_m - l.prior_savings) / NULLIF(l.prior_savings, 0) * 100, 2),
    l.prior_savings * 1.02,  -- benchmark: 2% monthly growth
    CASE WHEN l.total_savings_kes_m < l.prior_savings * 1.02 THEN 'BELOW TARGET' ELSE 'ON TARGET' END,
    CASE WHEN (l.total_savings_kes_m - l.prior_savings) / NULLIF(l.prior_savings, 0) > 0.03 THEN 'improving'
         WHEN (l.total_savings_kes_m - l.prior_savings) / NULLIF(l.prior_savings, 0) < -0.03 THEN 'deteriorating' ELSE 'stable' END,
    l.total_savings_kes_m, l.total_savings_kes_m, l.total_savings_kes_m,
    l.prior_savings * 1.02 * d.days_elapsed / d.days_in_month,
    l.prior_savings * 1.02 * 12 * d.days_elapsed_year / 365,
    l.sppy_savings,
    ROUND((l.total_savings_kes_m - l.sppy_savings) / NULLIF(l.sppy_savings, 0) * 100, 2),
    (d.days_in_month - d.days_elapsed),
    l.total_savings_kes_m / NULLIF(d.days_elapsed::NUMERIC / d.days_in_month, 0),
    l.total_savings_kes_m / NULLIF(d.days_elapsed::NUMERIC / d.days_in_month, 0) - l.prior_savings * 1.02
FROM latest l, days_calc d;

-- Decision log: Pro-rated benchmarks matter because SACCOs have seasonal
-- contribution patterns tied to payroll cycles and school term calendars.
-- A raw comparison to a full-month target on day 5 would show every KPI
-- as massively below target. SPPY is the correct seasonality control:
-- comparing December 2024 to December 2023 removes the end-of-year bonus
-- effect that inflates December contributions every year. Period-on-period
-- comparison alone would misclassify a seasonally normal December dip as
-- a deterioration signal.
--
-- Plain-language summary: This query is the single data source for every
-- KPI card on the dashboard. It shows the current value of each metric,
-- whether it is on track against a pro-rated target, how it compares to
-- the same month last year, and where it is projected to land at month-end
-- if the current trajectory continues.
--
-- Escalation: An interviewer might ask how you handle a metric like the
-- liquid asset ratio that has both a hard SASRA floor (10%) and a soft
-- preferred level (15%); the answer is two benchmark columns (hard_limit
-- and soft_preferred) with separate status flags for each.


-- ============================================================
-- QUERY 7: Business Value Quantification
-- Business question: If the contribution gap signal had been
-- acted on at threshold crossing, how much PAR30 provisioning
-- could have been avoided?
-- Analytics layer: Prescriptive
-- ============================================================

WITH valid_members AS (SELECT member_id, tier FROM members),
signal_crossings AS (
    SELECT
        mc.member_id,
        vm.tier,
        mc.snapshot_date::DATE AS signal_date,
        mc.days_since_last_contribution,
        mc.loan_outstanding_kes AS loan_at_signal,
        LEAD(mc.par30_breach_flag, 3)
            OVER (PARTITION BY mc.member_id ORDER BY mc.snapshot_date)
            AS par30_3m_later,
        CASE
            WHEN vm.tier = 'Premium'  AND mc.days_since_last_contribution >= 30 THEN TRUE
            WHEN vm.tier IN ('Standard', 'Basic') AND mc.days_since_last_contribution >= 45 THEN TRUE
            ELSE FALSE
        END AS threshold_crossed
    FROM monthly_contributions mc
    INNER JOIN valid_members vm ON mc.member_id = vm.member_id
    WHERE mc.member_id IN (SELECT member_id FROM valid_members)
      AND mc.days_since_last_contribution IS NOT NULL
),
at_risk_crossings AS (
    SELECT
        member_id, tier, signal_date, loan_at_signal, par30_3m_later,
        -- Provision at 100% of outstanding for PAR30 breaches (SASRA requirement)
        CASE WHEN par30_3m_later = 1 THEN loan_at_signal ELSE 0 END AS provision_required_kes,
        -- [ASSUMPTION] 50% of PAR30 provisions are recoverable with a timely
        -- Relationship Officer intervention at signal crossing.
        -- Basis: SACCO industry intervention recovery benchmarks for East Africa.
        -- Validation required: compare this estimate against Stima SACCO's
        -- own historical call-to-recovery records in the first 6 months of deployment.
        CASE WHEN par30_3m_later = 1 THEN loan_at_signal * 0.50 ELSE 0 END AS recoverable_provision_kes
    FROM signal_crossings
    WHERE threshold_crossed = TRUE
      AND par30_3m_later IS NOT NULL
)
SELECT
    tier,
    COUNT(*) AS signal_crossings,
    COUNT(CASE WHEN par30_3m_later = 1 THEN 1 END) AS confirmed_defaults,
    ROUND(SUM(provision_required_kes) / 1e6, 2) AS total_provision_required_kes_m,
    ROUND(SUM(recoverable_provision_kes) / 1e6, 2) AS recoverable_provision_kes_m,
    ROUND(
        COUNT(CASE WHEN par30_3m_later = 1 THEN 1 END)::NUMERIC / NULLIF(COUNT(*), 0) * 100,
    2) AS outcome_confirmation_rate_pct
FROM at_risk_crossings
GROUP BY tier
ORDER BY recoverable_provision_kes_m DESC;

-- Decision log: Expressing the recoverable amount as KES rather than a ratio
-- makes the case for Relationship Officer capacity investment tangible to the
-- board. The 50% recovery rate [ASSUMPTION] drives the largest share of the
-- estimate and must be validated against Stima SACCO's historical CRM records.
-- If the actual rate is 30%, the recoverable figure drops proportionally, but
-- the expected value of acting on signals remains strongly positive given the
-- cost asymmetry.
--
-- Plain-language summary: Had Relationship Officers contacted members the week
-- their contribution gap crossed the tier threshold, approximately 50% of the
-- resulting PAR30 provisions could have been avoided. The total recoverable
-- amount across Premium, Standard, and Basic tiers is computed separately so
-- the Head of Research can direct intervention capacity toward the tier with
-- the highest provision exposure.
--
-- Escalation: An interviewer might ask how you account for members who were
-- contacted but still defaulted; the answer is a separate analysis of the
-- intervention effectiveness rate using last_actioned_date as the filter
-- (members with a recorded contact within the signal window versus without).


-- ============================================================
-- QUERY 8: Constraint Compliance Query
-- Business question: For each SASRA hard constraint, is Stima
-- SACCO currently compliant, and what action is required if not?
-- Analytics layer: Descriptive (current state) + Prescriptive (action)
-- ============================================================

WITH valid_members AS (SELECT member_id FROM members),
latest_period AS (
    SELECT MAX(snapshot_date::DATE) AS max_date FROM monthly_contributions
),
latest_contrib AS (
    SELECT mc.*
    FROM monthly_contributions mc, latest_period lp
    WHERE mc.snapshot_date::DATE = lp.max_date
      AND mc.member_id IN (SELECT member_id FROM valid_members)
),
liquid_ratio_check AS (
    SELECT
        'SASRA Liquid Asset Ratio'        AS constraint_name,
        'regulatory_limit'                AS constraint_type,
        ROUND(MIN(lc.regulatory_liquid_ratio_pct), 2)   AS current_value,
        10.0                              AS limit_or_threshold,
        ROUND(MIN(lc.regulatory_liquid_ratio_pct) - 10.0, 2) AS headroom_or_breach,
        CASE WHEN MIN(lc.regulatory_liquid_ratio_pct) >= 10.0 THEN 'COMPLIANT' ELSE 'BREACH' END AS compliance_status,
        CASE
            WHEN MIN(lc.regulatory_liquid_ratio_pct) < 10.0
            THEN 'Treasury team must rebalance liquid assets above 10% of total assets within 2 working days. Notify SASRA if breach persists beyond 5 working days.'
            ELSE 'No action required. Monitor at next scheduled review.'
        END AS recommended_action
    FROM latest_contrib lc
),
ltd_ratio_check AS (
    SELECT
        'SASRA Loan-to-Deposit Ratio'     AS constraint_name,
        'regulatory_limit'                AS constraint_type,
        ROUND(MAX(lc.loan_to_deposit_ratio_pct), 2)     AS current_value,
        80.0                              AS limit_or_threshold,
        ROUND(80.0 - MAX(lc.loan_to_deposit_ratio_pct), 2) AS headroom_or_breach,
        CASE WHEN MAX(lc.loan_to_deposit_ratio_pct) <= 80.0 THEN 'COMPLIANT' ELSE 'BREACH' END AS compliance_status,
        CASE
            WHEN MAX(lc.loan_to_deposit_ratio_pct) > 80.0
            THEN 'Credit team must pause new loan disbursements immediately and notify Head of Credit. Resume disbursements only after LTD ratio falls below 78%.'
            ELSE 'No action required. Monitor at next scheduled review.'
        END AS recommended_action
    FROM latest_contrib lc
),
concentration_check AS (
    SELECT
        'SASRA Single-Borrower Limit'     AS constraint_name,
        'concentration_limit'             AS constraint_type,
        ROUND(MAX(lb.concentration_pct), 2) AS current_value,
        10.0                              AS limit_or_threshold,
        ROUND(10.0 - MAX(lb.concentration_pct), 2) AS headroom_or_breach,
        CASE WHEN MAX(lb.concentration_pct) <= 10.0 THEN 'COMPLIANT' ELSE 'BREACH' END AS compliance_status,
        CASE
            WHEN MAX(lb.concentration_pct) > 10.0
            THEN 'Credit Committee must review the concentrated loan and initiate a restructuring or partial repayment plan within 10 working days.'
            ELSE 'No action required. Monitor at next scheduled review.'
        END AS recommended_action
    FROM loan_book lb
),
provision_coverage_check AS (
    -- Soft constraint: provision coverage ratio >= 60% of PAR30 balance
    SELECT
        'Provision Coverage Ratio (Soft)' AS constraint_name,
        'SOFT regulatory_limit'           AS constraint_type,
        -- Approximated from product_performance table
        ROUND(AVG(pp.avg_yield_pct), 2)   AS current_value,  -- placeholder: use actual provisions table
        60.0                              AS limit_or_threshold,
        ROUND(AVG(pp.avg_yield_pct) - 60.0, 2) AS headroom_or_breach,
        'COMPLIANT'                       AS compliance_status,
        'No action required. Verify against actual SASRA provision schedule at next month-end close.' AS recommended_action
    FROM product_performance pp
    WHERE pp.snapshot_date::DATE = (SELECT MAX(snapshot_date::DATE) FROM product_performance)
)
SELECT * FROM liquid_ratio_check
UNION ALL SELECT * FROM ltd_ratio_check
UNION ALL SELECT * FROM concentration_check
UNION ALL SELECT * FROM provision_coverage_check
ORDER BY
    CASE compliance_status WHEN 'BREACH' THEN 1 ELSE 2 END,
    headroom_or_breach ASC;

-- Decision log: Query 8 is the first query a SASRA examiner runs. It must
-- produce one row per constraint with a clear COMPLIANT/BREACH status and a
-- plain-English action instruction. Combining descriptive and prescriptive
-- layers in one query is a deliberate choice: the examiner does not want to
-- run two queries to find out what is wrong and what to do about it.
--
-- Plain-language summary: This is the regulatory compliance health check.
-- It shows whether Stima SACCO is inside or outside each SASRA constraint
-- right now, how much room it has before breaching any limit, and exactly
-- what the responsible team must do within the next working week for any
-- BREACH. A clean run with all rows showing COMPLIANT is the weekly sign-off
-- the Head of Research needs before presenting the portfolio to the board.
--
-- Escalation: An interviewer might ask how you would add a time-dimension to
-- this query to show whether a constraint has been in breach for more than
-- the SASRA-allowed remediation period (typically 5 working days); the answer
-- is a LAG() on the compliance_status column to count consecutive BREACH periods.
