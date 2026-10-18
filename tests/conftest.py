"""A tiny CMS-format MLR public use file covering every reconciliation case."""

import csv
import io
import zipfile

import pytest

from mlrrecon.db import connect, migrate

HEADER_COLS = ["mr_submission_template_id", "business_state", "group_affiliation", "company_name",
               "naic_company_code", "not_for_profit", "merge_markets_ind_small_grp"]

# filing id -> (state, company, merged markets)
FILINGS = {
    1: ("IL", "Clean Large Group Co", 0),
    2: ("IL", "Rebate Owing Co", 0),
    3: ("MA", "Merged Market Plan", 1),
    4: ("PR", "Typo Insurance Co", 0),
    5: ("TX", "Mystery Health", 0),
    6: ("NM", "Runoff Health", 0),
    7: ("Grand Total", "Clean Large Group Co", 0),
}


def market_lines(num, den, den_cy, pre, cred, adj, std, rebate):
    return {"MLR_NUMERATOR": {"total": num}, "MLR_DENOMINATOR": {"total": den, "cy": den_cy},
            "PRELIMINARY_MLR": {"total": pre}, "CREDIBILITY_ADJUSTMENT_FACTOR": {"total": cred},
            "CREDIBILITY_ADJUSTED_MLR": {"total": adj}, "MLR_STANDARD": {"total": std},
            "REBATE_AMT_CREDIBILITY_ADJ_MLR": {"total": rebate},
            "PREMIUM_EARNED_INCLUDING_FSHRP": {"cy": den_cy}}


def default_data(mystery_rebate=99.0):
    merged = market_lines(800, 1000, 1000, 0.8, 0.0, 0.8, 0.88, None)
    return {
        1: {"cmm_large_group": market_lines(900, 1000, 400, 0.9, 0.0, 0.9, 0.85, 0)},
        2: {"cmm_large_group": market_lines(700, 1000, 500, 0.7, 0.01, 0.71, 0.8, 45.0)},
        # combined expected rebate (0.88 - 0.8) x 1000 = 80, split 30 + 50 between the two markets
        3: {"cmm_individual": {**merged, "REBATE_AMT_CREDIBILITY_ADJ_MLR": {"total": 30.0}},
            "cmm_small_group": {**merged, "REBATE_AMT_CREDIBILITY_ADJ_MLR": {"total": 50.0}}},
        4: {"cmm_large_group": market_lines(900, 1000, 400, 0.9, 0.0, 12345678.0, 0.85, 0)},  # $ in a ratio field
        5: {"cmm_small_group": market_lines(700, 1000, 100, 0.7, 0.0, 0.7, 0.8, mystery_rebate)},  # expected 10
        6: {"cmm_individual": market_lines(-50, -100, -5, 0.5, 0.0, 0.5, 0.8, 3.0)},  # rebate on negative premium
        7: {"cmm_large_group": market_lines(900, 1000, 400, 0.9, 0.0, 0.9, 0.85, 0)},  # roll-up: excluded
    }


def build_zip(path, data):
    markets = ["cmm_individual", "cmm_small_group", "cmm_large_group"]
    value_cols = [f"{m}_{p}" for m in markets for p in ("py2", "py1", "cy", "total")]
    h = io.StringIO()
    w = csv.writer(h)
    w.writerow(HEADER_COLS)
    for fid, (state, name, merged) in FILINGS.items():
        w.writerow([fid, state, "TEST GRP", name, f"{fid:05d}", 0, merged])
    p3 = io.StringIO()
    w = csv.writer(p3)
    w.writerow(["mr_submission_template_id", "row_lookup_code", *value_cols, "created_date"])
    w.writerow([999, "MLR_NUMERATOR", *[""] * len(value_cols), ""])  # orphan line: skipped
    for fid, by_market in data.items():
        codes = {c for lines in by_market.values() for c in lines}
        for code in sorted(codes):
            row = {}
            for m, lines in by_market.items():
                for period, v in (lines.get(code) or {}).items():
                    if v is not None:
                        row[f"{m}_{period}"] = v
            w.writerow([fid, code, *[row.get(c, "") for c in value_cols], "2025-01-01"])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("MR_Submission_Template_Header.csv", h.getvalue())
        z.writestr("Part3_MLR_Rebate_Calculation.csv", p3.getvalue())
    return path


@pytest.fixture()
def con():
    c = connect(":memory:")
    migrate(c)
    return c


@pytest.fixture()
def puf(tmp_path):
    return build_zip(tmp_path / "mlr-public-use-file-2024.zip", default_data())
