# MLR Recon — Health Insurer Finance Reconciliation
Tech: Python, SQL, SQLite, FastAPI, Excel (openpyxl), pytest, GitHub Actions
- Built a finance reconciliation app over CMS Medical Loss Ratio data, recomputing the MLR and ACA rebate for 2,602 insurer state filings (2023–2024) from their components in SQL.
- Ran 8,394 automated checks that flagged 36 exceptions, including data-entry errors in federal filings, and tracked each through an open/investigating/resolved workflow with an audit trail.
- Designed versioned SQL schema migrations and idempotent yearly loads; reloads auto-resolve corrected exceptions and reopen regressions.
- Generated Excel reports with live formulas for audit and a dashboard ranking an insurer's MLR against state peers.
