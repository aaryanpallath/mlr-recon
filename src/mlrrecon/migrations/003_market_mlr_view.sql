-- One row per filing x market with the Part 3 figures pivoted into columns, so reconciliation and
-- reports read plain columns instead of re-pivoting the long table each time.
CREATE VIEW market_mlr AS
SELECT
    r.reporting_year,
    r.filing_id,
    r.market,
    MAX(CASE WHEN r.line_code = 'MLR_NUMERATOR'                  AND r.period = 'total' THEN r.value END) AS numerator,
    MAX(CASE WHEN r.line_code = 'MLR_DENOMINATOR'                AND r.period = 'total' THEN r.value END) AS denominator,
    MAX(CASE WHEN r.line_code = 'MLR_DENOMINATOR'                AND r.period = 'cy'    THEN r.value END) AS denominator_cy,
    MAX(CASE WHEN r.line_code = 'PRELIMINARY_MLR'                AND r.period = 'total' THEN r.value END) AS preliminary_mlr,
    MAX(CASE WHEN r.line_code = 'CREDIBILITY_ADJUSTMENT_FACTOR'  AND r.period = 'total' THEN r.value END) AS credibility_adjustment,
    MAX(CASE WHEN r.line_code = 'CREDIBILITY_ADJUSTED_MLR'       AND r.period = 'total' THEN r.value END) AS adjusted_mlr,
    MAX(CASE WHEN r.line_code = 'MLR_STANDARD'                   AND r.period = 'total' THEN r.value END) AS mlr_standard,
    MAX(CASE WHEN r.line_code = 'REBATE_AMT_CREDIBILITY_ADJ_MLR' AND r.period = 'total' THEN r.value END) AS rebate,
    MAX(CASE WHEN r.line_code = 'PREMIUM_EARNED_INCLUDING_FSHRP' AND r.period = 'cy'    THEN r.value END) AS earned_premium_cy,
    MAX(CASE WHEN r.line_code = 'ADJ_INCURRED_CLAIMS'            AND r.period = 'cy'    THEN r.value END) AS incurred_claims_cy
FROM rebate_lines r
GROUP BY r.reporting_year, r.filing_id, r.market;
