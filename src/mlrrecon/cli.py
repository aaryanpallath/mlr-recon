"""Command line: `mlr run` loads every year in data/raw, reconciles, and writes results/ (JSON + Excel)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .db import DEFAULT_DB, connect, migrate
from .ingest import ingest_zip, year_from_name
from .recon import reconcile
from .report import peer_view, write_workbook


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="mlr", description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply pending schema migrations")
    ing = sub.add_parser("ingest", help="load CMS MLR public use file zips")
    ing.add_argument("files", nargs="+", type=Path)
    rec = sub.add_parser("reconcile", help="recompute MLR/rebates and update exceptions")
    rec.add_argument("--year", type=int, required=True)
    run = sub.add_parser("run", help="ingest data/raw/*.zip, reconcile each year, write results/")
    run.add_argument("--raw", type=Path, default=Path("data/raw"))
    run.add_argument("--out", type=Path, default=Path("results"))
    srv = sub.add_parser("serve", help="run the dashboard")
    srv.add_argument("--port", type=int, default=8000)
    a = p.parse_args(argv)

    con = connect(a.db)
    applied = migrate(con)
    if a.cmd == "migrate":
        print(f"applied: {applied or 'nothing (up to date)'}")
    elif a.cmd == "ingest":
        for f in a.files:
            print(json.dumps(ingest_zip(con, f)))
    elif a.cmd == "reconcile":
        print(json.dumps(reconcile(con, a.year), indent=2))
    elif a.cmd == "run":
        a.out.mkdir(parents=True, exist_ok=True)
        for f in sorted(a.raw.glob("*.zip"), key=year_from_name):
            load = ingest_zip(con, f)
            summary = reconcile(con, load["year"])
            hcsc = peer_view(con, load["year"], "Health Care Service Corporation")
            summary["load"] = {k: v for k, v in load.items() if k != "year"}
            summary["hcsc_peer_view"] = hcsc
            (a.out / f"reconciliation_{load['year']}.json").write_text(json.dumps(summary, indent=2) + "\n")
            write_workbook(con, load["year"], summary, a.out / f"mlr_report_{load['year']}.xlsx")
            print(f"{load['year']}: {load['filings']} filings, {summary['exceptions']} exceptions "
                  f"{summary['exceptions_by_category']}")
    elif a.cmd == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(a.db), host="127.0.0.1", port=a.port)


if __name__ == "__main__":
    main()
