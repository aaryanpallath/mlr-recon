-- Reconciliation exceptions (defects) with a status workflow and an audit trail of every change.
CREATE TABLE exceptions (
    id             INTEGER PRIMARY KEY,
    reporting_year INTEGER NOT NULL,
    filing_id      INTEGER NOT NULL,
    market         TEXT    NOT NULL,
    check_name     TEXT    NOT NULL,             -- preliminary_mlr | adjusted_mlr | rebate
    reported       REAL,
    expected       REAL,
    difference     REAL,
    category       TEXT    NOT NULL,             -- merged_markets | nonpositive_premium | unexplained
    status         TEXT    NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'investigating', 'resolved', 'accepted')),
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    -- No foreign key to filings on purpose: exceptions and their history survive a reload of the year.
    UNIQUE (reporting_year, filing_id, market, check_name)
);

CREATE TABLE exception_events (
    id           INTEGER PRIMARY KEY,
    exception_id INTEGER NOT NULL REFERENCES exceptions (id) ON DELETE CASCADE,
    from_status  TEXT,
    to_status    TEXT    NOT NULL,
    note         TEXT,
    actor        TEXT    NOT NULL DEFAULT 'system',
    at           TEXT    NOT NULL DEFAULT (datetime('now'))
);
