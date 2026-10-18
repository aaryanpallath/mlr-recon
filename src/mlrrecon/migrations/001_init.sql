-- Core tables: one row per insurer filing (company x state x reporting year) and the MLR/rebate
-- calculation lines from Part 3 of the CMS MLR Annual Reporting Form, stored long (one value per row).
CREATE TABLE filings (
    reporting_year    INTEGER NOT NULL,
    filing_id         INTEGER NOT NULL,          -- CMS mr_submission_template_id
    state             TEXT    NOT NULL,          -- business_state; 'Grand Total' = company-wide roll-up
    company_name      TEXT    NOT NULL,
    group_affiliation TEXT,
    naic_company_code TEXT,
    not_for_profit    INTEGER,
    merged_markets    INTEGER NOT NULL DEFAULT 0, -- state merges individual + small group markets
    PRIMARY KEY (reporting_year, filing_id)
);

CREATE TABLE rebate_lines (
    reporting_year INTEGER NOT NULL,
    filing_id      INTEGER NOT NULL,
    line_code      TEXT    NOT NULL,             -- e.g. MLR_NUMERATOR, CREDIBILITY_ADJUSTED_MLR
    market         TEXT    NOT NULL,             -- e.g. cmm_individual, cmm_large_group
    period         TEXT    NOT NULL,             -- py2, py1, cy (reporting year), total (3-year), rc
    value          REAL    NOT NULL,
    PRIMARY KEY (reporting_year, filing_id, line_code, market, period),
    FOREIGN KEY (reporting_year, filing_id) REFERENCES filings (reporting_year, filing_id) ON DELETE CASCADE
);

CREATE TABLE ingest_runs (
    id             INTEGER PRIMARY KEY,
    reporting_year INTEGER NOT NULL,
    source_file    TEXT    NOT NULL,
    sha256         TEXT    NOT NULL,
    filings        INTEGER NOT NULL,
    lines          INTEGER NOT NULL,
    skipped_lines  INTEGER NOT NULL,
    loaded_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
