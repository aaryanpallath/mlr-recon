"""Recompute each filing's MLR and rebate from its components and track mismatches as exceptions.

Checks, per state filing and market (federal MLR rule, 45 CFR 158):
  preliminary_mlr  numerator / denominator (3-year totals)
  adjusted_mlr     preliminary MLR + credibility adjustment
  rebate           max(0, (MLR standard - adjusted MLR) x reporting-year denominator)

A mismatch becomes an exception with a category explaining the likely cause (non-positive premium,
implausible value such as a dollar amount in a ratio field, merged individual/small-group market, or
unexplained). Re-running after the data
changes updates open exceptions, and auto-resolves ones that now pass, with every change logged.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# MLRs are reported rounded to three decimals, so a sum of two rounded terms can be off by up to 0.001.
RATIO_TOLERANCE = 0.0015
PLAUSIBLE_MLR = (0.0, 5.0)  # an MLR outside this range is a data-entry error, not a calculation difference
INDIVIDUAL_SMALL_GROUP = ("cmm_individual", "cmm_small_group")

TRANSITIONS = {
    "open": {"investigating", "resolved", "accepted"},
    "investigating": {"open", "resolved", "accepted"},
    "resolved": {"open"},
    "accepted": {"open"},
}


@dataclass
class Finding:
    filing_id: int
    market: str
    check_name: str
    reported: float
    expected: float

    @property
    def difference(self) -> float:
        return self.reported - self.expected


def dollar_tolerance(amount: float) -> float:
    return max(1.0, 0.001 * abs(amount))


def check_row(r: sqlite3.Row) -> tuple[list[str], list[Finding]]:
    """Return (checks performed, failed checks) for one market_mlr row."""
    done, failed = [], []
    num, den, pre = r["numerator"], r["denominator"], r["preliminary_mlr"]
    if num is not None and den not in (None, 0) and pre is not None:
        done.append("preliminary_mlr")
        if abs(num / den - pre) > RATIO_TOLERANCE:
            failed.append(Finding(r["filing_id"], r["market"], "preliminary_mlr", pre, num / den))
    adj, cred = r["adjusted_mlr"], r["credibility_adjustment"]
    if pre is not None and cred is not None and adj is not None:
        done.append("adjusted_mlr")
        if abs(pre + cred - adj) > RATIO_TOLERANCE:
            failed.append(Finding(r["filing_id"], r["market"], "adjusted_mlr", adj, pre + cred))
    std, reb, den_cy = r["mlr_standard"], r["rebate"], r["denominator_cy"]
    if None not in (std, reb, den_cy, adj):
        done.append("rebate")
        expected = max(0.0, (std - adj) * den_cy)
        if abs(expected - reb) > dollar_tolerance(reb):
            failed.append(Finding(r["filing_id"], r["market"], "rebate", reb, expected))
    return done, failed


def categorize(f: Finding, r: sqlite3.Row, merged_markets: bool) -> str:
    if (r["denominator_cy"] is not None and r["denominator_cy"] <= 0) or (r["denominator"] or 1) <= 0:
        return "nonpositive_premium"
    lo, hi = PLAUSIBLE_MLR
    ratio = f.reported if f.check_name != "rebate" else r["adjusted_mlr"]
    if ratio is not None and not (lo < ratio <= hi):
        return "implausible_value"
    if merged_markets and f.market in INDIVIDUAL_SMALL_GROUP:
        return "merged_markets"
    return "unexplained"


def reconcile(con: sqlite3.Connection, year: int) -> dict:
    rows = con.execute(
        "SELECT m.*, f.merged_markets FROM market_mlr m JOIN filings f USING (reporting_year, filing_id) "
        "WHERE m.reporting_year = ? AND f.state <> 'Grand Total'", (year,)).fetchall()
    checked: dict[str, int] = {}
    failing: dict[tuple, tuple[Finding, str]] = {}
    for r in rows:
        done, failed = check_row(r)
        for c in done:
            checked[c] = checked.get(c, 0) + 1
        for f in failed:
            failing[(f.filing_id, f.market, f.check_name)] = (f, categorize(f, r, bool(r["merged_markets"])))
    split_verified = verify_merged_splits(failing)

    with con:
        existing = {(e["filing_id"], e["market"], e["check_name"]): e for e in con.execute(
            "SELECT * FROM exceptions WHERE reporting_year = ?", (year,))}
        for key, (f, cat) in failing.items():
            e = existing.get(key)
            if e is None:
                cur = con.execute(
                    "INSERT INTO exceptions (reporting_year, filing_id, market, check_name, reported, expected, "
                    "difference, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (year, f.filing_id, f.market, f.check_name, f.reported, f.expected, f.difference, cat))
                _event(con, cur.lastrowid, None, "open", "detected by reconciliation")
            else:
                con.execute("UPDATE exceptions SET reported = ?, expected = ?, difference = ?, category = ?, "
                            "updated_at = datetime('now') WHERE id = ?",
                            (f.reported, f.expected, f.difference, cat, e["id"]))
                if e["status"] == "resolved":  # it came back: reopen
                    _set(con, e["id"], "resolved", "open", "failing again on re-run")
        for key, e in existing.items():
            if key not in failing and e["status"] in ("open", "investigating"):
                _set(con, e["id"], e["status"], "resolved", "passes on re-run")

    by_cat: dict[str, int] = {}
    for _f, cat in failing.values():
        by_cat[cat] = by_cat.get(cat, 0) + 1
    totals = con.execute(
        "SELECT COUNT(DISTINCT m.filing_id) AS filings, SUM(m.rebate) AS rebates, "
        "SUM(CASE WHEN m.rebate > 0 THEN 1 ELSE 0 END) AS markets_owing "
        "FROM market_mlr m JOIN filings f USING (reporting_year, filing_id) "
        "WHERE m.reporting_year = ? AND f.state <> 'Grand Total' AND m.rebate IS NOT NULL", (year,)).fetchone()
    return {
        "reporting_year": year,
        "checks_run": checked,
        "checks_passed": {c: n - sum(1 for k in failing if k[2] == c) for c, n in checked.items()},
        "merged_market_rebate_splits_verified": split_verified,
        "exceptions": len(failing),
        "exceptions_by_category": dict(sorted(by_cat.items())),
        "filings_with_rebate_data": totals["filings"],
        "market_filings_owing_rebates": totals["markets_owing"],
        "total_rebates_reported_usd": round(totals["rebates"] or 0, 2),
    }


def verify_merged_splits(failing: dict[tuple, tuple[Finding, str]]) -> int:
    """In states that merge the individual and small group markets, one rebate is computed for the combined
    market and then split between the two. If the two reported rebates add up to the combined expected
    rebate, the split is correct: drop both from `failing` and return how many filings were verified."""
    verified = 0
    for fid in {k[0] for k, (_f, cat) in failing.items() if cat == "merged_markets" and k[2] == "rebate"}:
        keys = [(fid, m, "rebate") for m in INDIVIDUAL_SMALL_GROUP]
        if not all(k in failing for k in keys):
            continue
        parts = [failing[k][0] for k in keys]
        combined = sum(f.reported for f in parts)
        if abs(combined - parts[0].expected) <= dollar_tolerance(parts[0].expected):
            for k in keys:
                del failing[k]
            verified += 1
    return verified


def set_status(con: sqlite3.Connection, exception_id: int, to_status: str, note: str | None = None,
               actor: str = "user") -> None:
    row = con.execute("SELECT status FROM exceptions WHERE id = ?", (exception_id,)).fetchone()
    if row is None:
        raise KeyError(exception_id)
    if to_status not in TRANSITIONS[row["status"]]:
        raise ValueError(f"cannot move an exception from {row['status']} to {to_status}")
    with con:
        _set(con, exception_id, row["status"], to_status, note, actor)


def _set(con, eid: int, frm: str | None, to: str, note: str | None, actor: str = "system") -> None:
    con.execute("UPDATE exceptions SET status = ?, note = COALESCE(?, note), updated_at = datetime('now') "
                "WHERE id = ?", (to, note, eid))
    _event(con, eid, frm, to, note, actor)


def _event(con, eid: int, frm: str | None, to: str, note: str | None, actor: str = "system") -> None:
    con.execute("INSERT INTO exception_events (exception_id, from_status, to_status, note, actor) "
                "VALUES (?, ?, ?, ?, ?)", (eid, frm, to, note, actor))
