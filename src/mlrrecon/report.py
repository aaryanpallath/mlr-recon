"""Finance reporting: SQL queries behind the dashboard, and an Excel workbook built from them.

In the workbook, every derived figure (MLR, expected rebate, difference) is an Excel formula over the raw
components in the same row, so a reviewer can audit the numbers in Excel without trusting this code.
"""

from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

MARKET_LABELS = {
    "cmm_individual": "Individual", "cmm_small_group": "Small group", "cmm_large_group": "Large group",
}
STATE_FILTER = "f.state <> 'Grand Total'"


def state_summary(con: sqlite3.Connection, year: int) -> list[sqlite3.Row]:
    """Premium-weighted MLR and rebates per state and comprehensive major-medical market."""
    return con.execute(f"""
        SELECT f.state, m.market, COUNT(*) AS insurers,
               SUM(m.numerator) AS numerator, SUM(m.denominator) AS denominator,
               SUM(m.earned_premium_cy) AS earned_premium_cy, SUM(COALESCE(m.rebate, 0)) AS rebates,
               SUM(CASE WHEN m.rebate > 0 THEN 1 ELSE 0 END) AS insurers_owing
        FROM market_mlr m JOIN filings f USING (reporting_year, filing_id)
        WHERE m.reporting_year = ? AND {STATE_FILTER} AND m.market IN ('cmm_individual','cmm_small_group',
              'cmm_large_group') AND m.denominator > 0
        GROUP BY f.state, m.market ORDER BY f.state, m.market""", (year,)).fetchall()


def peer_view(con: sqlite3.Connection, year: int, company_like: str) -> list[dict]:
    """A company's credibility-adjusted MLR in each state/market it files, against the other insurers there."""
    rows = con.execute(f"""
        SELECT f.state, m.market, f.company_name, m.adjusted_mlr, m.mlr_standard, m.rebate, m.earned_premium_cy
        FROM market_mlr m JOIN filings f USING (reporting_year, filing_id)
        WHERE m.reporting_year = ? AND {STATE_FILTER} AND m.adjusted_mlr > 0 AND m.adjusted_mlr <= 5
              AND m.market IN ('cmm_individual','cmm_small_group','cmm_large_group')""", (year,)).fetchall()
    target = [r for r in rows if company_like.lower() in r["company_name"].lower()]
    out = []
    for t in sorted(target, key=lambda r: (r["state"], r["market"])):
        peers = sorted(r["adjusted_mlr"] for r in rows if r["state"] == t["state"] and r["market"] == t["market"]
                       and r["company_name"] != t["company_name"])
        median = statistics.median(peers) if peers else None
        out.append({
            "state": t["state"], "market": MARKET_LABELS.get(t["market"], t["market"]), "company": t["company_name"],
            "adjusted_mlr": t["adjusted_mlr"], "mlr_standard": t["mlr_standard"], "peer_median_mlr": median,
            "peers": len(peers), "rank_high_to_low": 1 + sum(1 for p in peers if p > t["adjusted_mlr"]),
            "rebate": t["rebate"], "earned_premium_cy": t["earned_premium_cy"],
        })
    return out


def exceptions(con: sqlite3.Connection, year: int, status: str | None = None,
               category: str | None = None) -> list[sqlite3.Row]:
    q = """SELECT e.*, f.state, f.company_name, m.numerator, m.denominator, m.denominator_cy, m.preliminary_mlr,
                  m.credibility_adjustment, m.adjusted_mlr, m.mlr_standard, m.rebate
           FROM exceptions e JOIN filings f USING (reporting_year, filing_id)
           LEFT JOIN market_mlr m ON m.reporting_year = e.reporting_year AND m.filing_id = e.filing_id
                                 AND m.market = e.market
           WHERE e.reporting_year = ?"""
    args: list = [year]
    if status:
        q += " AND e.status = ?"
        args.append(status)
    if category:
        q += " AND e.category = ?"
        args.append(category)
    return con.execute(q + " ORDER BY e.category, f.state, f.company_name", args).fetchall()


# ---------------------------------------------------------------------------------------------- Excel

HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1F3864")
USD, PCT, RATIO = '"$"#,##0', "0.0%", "0.000"


def _sheet(wb: Workbook, title: str, headers: list[str], widths: list[int]):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for i, w in enumerate(widths, 1):
        ws.cell(1, i).font, ws.cell(1, i).fill = HEAD, HEAD_FILL
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return ws


def write_workbook(con: sqlite3.Connection, year: int, summary: dict, path: str | Path,
                   peer_company: str = "Health Care Service Corporation") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"MLR reconciliation — reporting year {year}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Source: CMS Medical Loss Ratio public use file (state filings; company roll-ups excluded)"])
    ws.append([])
    for label, value in [
        ("Filings with rebate data", summary["filings_with_rebate_data"]),
        ("Market filings owing rebates", summary["market_filings_owing_rebates"]),
        ("Total rebates reported", summary["total_rebates_reported_usd"]),
        ("Exceptions", summary["exceptions"]),
        *[(f"  {k.replace('_', ' ')}", v) for k, v in summary["exceptions_by_category"].items()],
        *[(f"Checks passed: {k.replace('_', ' ')}", f"{summary['checks_passed'][k]} of {n}")
          for k, n in summary["checks_run"].items()],
    ]:
        ws.append([label, value])
    ws["B6"].number_format = USD
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 38, 22

    st = _sheet(wb, "By State", ["State", "Market", "Insurers", "MLR numerator (3-yr)", "MLR denominator (3-yr)",
                                 "Weighted MLR", "Earned premium (yr)", "Rebates", "Insurers owing"],
                [8, 14, 10, 22, 22, 14, 20, 16, 14])
    for i, r in enumerate(state_summary(con, year), start=2):
        st.append([r["state"], MARKET_LABELS.get(r["market"], r["market"]), r["insurers"], r["numerator"],
                   r["denominator"], f"=IFERROR(D{i}/E{i},\"\")", r["earned_premium_cy"], r["rebates"],
                   r["insurers_owing"]])
        for c in "DEGH":
            st[f"{c}{i}"].number_format = USD
        st[f"F{i}"].number_format = PCT
    st.auto_filter.ref = st.dimensions

    pv = _sheet(wb, "Peer View", ["State", "Market", "Company", "Adjusted MLR", "MLR standard", "Peer median MLR",
                                  "Peers", "Rank (high→low)", "Rebate", "Earned premium (yr)"],
                [8, 14, 40, 14, 14, 16, 8, 14, 14, 20])
    for r in peer_view(con, year, peer_company):
        pv.append([r["state"], r["market"], r["company"], r["adjusted_mlr"], r["mlr_standard"],
                   r["peer_median_mlr"], r["peers"], r["rank_high_to_low"], r["rebate"], r["earned_premium_cy"]])
        row = pv.max_row
        for c in "DEF":
            pv[f"{c}{row}"].number_format = PCT
        for c in "IJ":
            pv[f"{c}{row}"].number_format = USD

    ex = _sheet(wb, "Exceptions", ["ID", "State", "Company", "Market", "Check", "Category", "Status",
                                   "Numerator", "Denominator", "Denominator (yr)", "Preliminary MLR",
                                   "Credibility adj.", "Adjusted MLR", "MLR standard", "Reported",
                                   "Expected (formula)", "Difference (formula)"],
                [6, 7, 36, 16, 16, 18, 13, 16, 16, 16, 14, 14, 14, 13, 16, 18, 18])
    for i, e in enumerate(exceptions(con, year), start=2):
        expected = {
            "preliminary_mlr": f"=IFERROR(H{i}/I{i},\"\")",
            "adjusted_mlr": f"=K{i}+L{i}",
            "rebate": f"=MAX(0,(N{i}-M{i})*J{i})",
        }[e["check_name"]]
        ex.append([e["id"], e["state"], e["company_name"], MARKET_LABELS.get(e["market"], e["market"]),
                   e["check_name"].replace("_", " "), e["category"].replace("_", " "), e["status"],
                   e["numerator"], e["denominator"], e["denominator_cy"], e["preliminary_mlr"],
                   e["credibility_adjustment"], e["adjusted_mlr"], e["mlr_standard"], e["reported"],
                   expected, f"=IFERROR(O{i}-P{i},\"\")"])
        fmt = USD if e["check_name"] == "rebate" else RATIO
        for c in "OPQ":
            ex[f"{c}{i}"].number_format = fmt
        for c in "HIJ":
            ex[f"{c}{i}"].number_format = USD
    ex.auto_filter.ref = ex.dimensions

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
