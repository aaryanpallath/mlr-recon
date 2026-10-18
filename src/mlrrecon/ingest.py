"""Load a CMS MLR public use file (zip) for one reporting year into the database.

Only the filing header and Part 3 (the MLR and rebate calculation) are loaded. A re-run for the same year
replaces that year's data in one transaction, so a partial or repeated load never leaves duplicates.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import zipfile
from pathlib import Path

HEADER_FILE = "MR_Submission_Template_Header.csv"
PART3_FILE = "Part3_MLR_Rebate_Calculation.csv"

MARKETS = (
    "cmm_individual", "cmm_small_group", "cmm_large_group",
    "mini_med_individual", "mini_med_small_group", "mini_med_large_group",
    "expatriate_small_group", "expatriate_large_group", "shp_individual",
)
PERIODS = ("py2", "py1", "cy", "total", "rc")


def parse_column(col: str) -> tuple[str, str] | None:
    """'cmm_small_group_cy' -> ('cmm_small_group', 'cy'); non-value columns -> None."""
    for market in MARKETS:
        if col.startswith(market + "_"):
            period = col[len(market) + 1:]
            if period in PERIODS:
                return market, period
    return None


def year_from_name(path: Path) -> int:
    m = re.search(r"(20\d{2})", path.name)
    if not m:
        raise ValueError(f"cannot infer reporting year from {path.name}; pass year explicitly")
    return int(m.group(1))


def _open_csv(z: zipfile.ZipFile, name: str) -> csv.DictReader:
    member = next((n for n in z.namelist() if n.rsplit("/", 1)[-1] == name), None)
    if member is None:
        raise ValueError(f"{name} not found in archive")
    return csv.DictReader(io.TextIOWrapper(z.open(member), encoding="latin-1", newline=""))


def _num(s: str | None) -> float | None:
    if s is None or s.strip() == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def ingest_zip(con: sqlite3.Connection, path: str | Path, year: int | None = None) -> dict:
    path = Path(path)
    year = year or year_from_name(path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as z:
        filings = [
            (year, int(r["mr_submission_template_id"]), r["business_state"].strip(), r["company_name"].strip(),
             (r.get("group_affiliation") or "").strip() or None, (r.get("naic_company_code") or "").strip() or None,
             int(r["not_for_profit"]) if (r.get("not_for_profit") or "").strip() else None,
             1 if (r.get("merge_markets_ind_small_grp") or "0").strip() == "1" else 0)
            for r in _open_csv(z, HEADER_FILE)
        ]
        known = {f[1] for f in filings}
        lines, skipped = [], 0
        for r in _open_csv(z, PART3_FILE):
            fid = int(r["mr_submission_template_id"])
            if fid not in known:
                skipped += 1
                continue
            for col, raw in r.items():
                key = parse_column(col) if col else None
                val = _num(raw) if key else None
                if key and val is not None:
                    lines.append((year, fid, r["row_lookup_code"], key[0], key[1], val))

    with con:  # one transaction: replace the whole year or nothing
        con.execute("DELETE FROM filings WHERE reporting_year = ?", (year,))
        con.executemany("INSERT INTO filings VALUES (?, ?, ?, ?, ?, ?, ?, ?)", filings)
        con.executemany("INSERT OR REPLACE INTO rebate_lines VALUES (?, ?, ?, ?, ?, ?)", lines)
        con.execute("INSERT INTO ingest_runs (reporting_year, source_file, sha256, filings, lines, skipped_lines) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (year, path.name, sha, len(filings), len(lines), skipped))
    return {"year": year, "filings": len(filings), "lines": len(lines), "skipped_lines": skipped, "sha256": sha}
