# MLR Recon — Health Insurer Medical Loss Ratio Reconciliation

A finance application over the federal **Medical Loss Ratio (MLR)** filings that every US health insurer
submits to CMS. It loads the filings into a versioned SQL database, recomputes each insurer's MLR and
rebate from its components, tracks every mismatch as an exception with a status workflow, and produces
an auditable Excel report and a web dashboard.

Under the Affordable Care Act, insurers must spend at least 80% (individual / small group) or 85%
(large group) of premium on medical care and quality improvement, or refund the difference to customers.
This project checks that math for every filing.

## Overview

| | 2023 | 2024 |
|---|---|---|
| Filing records loaded (incl. company roll-ups) | 2,303 | 2,194 |
| State filings with rebate data | 1,331 | 1,271 |
| Reconciliation checks run | 4,117 | 4,277 |
| Checks passed | 4,099 | 4,259 |
| Merged-market rebate splits verified | 4 | 5 |
| Exceptions | 18 | 18 |
| Rebates owed (all markets) | $967.2M | $1.65B |

Exceptions by cause (2023 / 2024): non-positive premium 9 / 9, implausible value 6 / 2, unexplained 3 / 7.
All figures are from `results/reconciliation_<year>.json`.

**Peer view.** For any insurer, the dashboard ranks its credibility-adjusted MLR against every other insurer
in the same state and market. Health Care Service Corporation (Blue Cross and Blue Shield of IL, MT, NM, OK,
TX) cleared the MLR standard in all 15 of its state markets in both years, on $37.9B (2023) and $45.1B
(2024) of earned premium, and owed no rebates.

## Architecture

```
CMS MLR public use file (zip)          SQLite (versioned migrations)            outputs
  MR_Submission_Template_Header.csv ─▶ filings          ─┐
  Part3_MLR_Rebate_Calculation.csv  ─▶ rebate_lines      ├▶ market_mlr (view) ─▶ reconcile ─▶ exceptions
                                       ingest_runs      ─┘                         │           exception_events
                                                                                   ├▶ results/*.json
                                                                                   ├▶ results/*.xlsx (Excel)
                                                                                   └▶ FastAPI dashboard
```

- `migrations/` — numbered SQL files applied in order, each in its own transaction, recorded in
  `schema_migrations`.
- `ingest.py` — loads one reporting year; a reload replaces that year atomically (no duplicates, no partial loads).
- `recon.py` — the checks, exception categories, auto-resolution and the status workflow.
- `report.py` — state summary, peer view, and the Excel workbook.
- `web.py` — dashboard and exceptions queue.

## Setup

```bash
uv venv && uv pip install -e ".[dev]"        # or: python -m venv .venv && pip install -e ".[dev]"
mkdir -p data/raw
curl -L -o data/raw/mlr-public-use-file-2024.zip https://www.cms.gov/files/zip/mlr-public-use-file-2024.zip
curl -L -o data/raw/mlr-public-use-file-2023.zip https://www.cms.gov/files/zip/mlr-public-use-file-2023.zip
```

## Usage

```bash
mlr run                  # migrate, load every year in data/raw, reconcile, write results/ (~5 s)
mlr serve                # dashboard at http://127.0.0.1:8000
mlr reconcile --year 2024
```

## Design decisions

- **Recompute, don't trust.** For each filing and market: preliminary MLR = numerator ÷ denominator
  (3-year totals); adjusted MLR = preliminary + credibility adjustment; rebate = max(0, (standard − adjusted
  MLR) × reporting-year denominator), per 45 CFR Part 158.
- **Tolerances match how CMS reports.** MLRs are rounded to three decimals, so ratio checks allow 0.0015;
  dollar checks allow $1 or 0.1%, whichever is larger.
- **Categorize every exception.** `nonpositive_premium` (zero or negative premium, e.g. a plan in run-off),
  `implausible_value` (an MLR outside 0–500%, e.g. a dollar amount typed into a ratio field), `unexplained`.
- **Verify merged markets instead of flagging them.** States that merge the individual and small group
  markets compute one rebate and split it. When the two reported rebates add up to the combined expected
  rebate, both pass.
- **Exceptions outlive reloads.** They have no foreign key to filings, so reloading a year keeps their status and
  history. Re-running reconciliation auto-resolves exceptions that now pass and reopens ones that fail again,
  each change logged in `exception_events`.
- **Status workflow.** open → investigating → resolved / accepted (accepted = explained, no correction
  needed); invalid moves are rejected.
- **Auditable Excel.** Weighted MLR, expected values and differences in the workbook are live Excel formulas
  over the raw components in the same row, so a reviewer can verify them without this code.

## Results

`results/reconciliation_2023.json` and `results/reconciliation_2024.json` hold the full summaries (checks run
and passed, exceptions by category, rebates, HCSC peer view). `results/mlr_report_<year>.xlsx` are the generated
Excel reports. Examples the checks surfaced in the 2024 data: an adjusted MLR reported as 27,706,828.99
(a premium amount in a ratio field), and a preliminary and adjusted MLR that appear swapped (1.328 / 1.06).

## Limitations

- Covers Part 3 (MLR and rebate calculation) only; Parts 1–2 (premium and claims detail) and Part 4 (rebate
  disbursement) are not loaded.
- `unexplained` exceptions are flagged for review, not diagnosed.
- Single-user dashboard with no authentication; SQLite rather than a server database.

## Testing

```bash
pytest          # 9 tests on a hand-built CMS-format fixture, offline, < 1 s
ruff check .
```

Covers migrations, idempotent loading, every exception category, merged-market verification,
auto-resolve and reopen on reload, the status workflow, peer ranking, Excel formulas and the web API.
GitHub Actions runs lint and tests on every push.

## Data & licensing

Data: CMS Medical Loss Ratio public use files
([cms.gov](https://www.cms.gov/marketplace/resources/data/medical-loss-ratio-data-systems-resources)), US
government data. Not committed; download as shown above. Code: MIT (see `LICENSE`).

## AI assistance disclosure

Built with help from Claude (Anthropic) via Claude Code; I reviewed, tested and verified the code and the
reconciliation results.
