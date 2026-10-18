"""Dashboard: headline figures, state breakdown, peer view, and the exceptions queue with status updates."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import recon, report
from .db import DEFAULT_DB, connect, migrate

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["usd"] = lambda v: "" if v is None else f"${v:,.0f}"
TEMPLATES.env.filters["pct"] = lambda v: "" if v is None else f"{v:.1%}"
TEMPLATES.env.filters["label"] = lambda v: report.MARKET_LABELS.get(v, (v or "").replace("_", " "))


def create_app(db_path: str | Path = DEFAULT_DB, peer_company: str = "Health Care Service Corporation") -> FastAPI:
    con = connect(db_path)
    migrate(con)
    app = FastAPI(title="MLR Reconciliation")

    def years() -> list[int]:
        return [r[0] for r in con.execute("SELECT DISTINCT reporting_year FROM filings ORDER BY 1 DESC")]

    def pick_year(year: int | None) -> int:
        ys = years()
        if not ys:
            raise HTTPException(404, "no data loaded; run `mlr run`")
        return year if year in ys else ys[0]

    def counts(year: int) -> dict:
        rows = con.execute("SELECT status, category, COUNT(*) n FROM exceptions WHERE reporting_year = ? "
                           "GROUP BY status, category", (year,)).fetchall()
        return {"by_status": _sum(rows, "status"), "by_category": _sum(rows, "category")}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, year: int | None = None):
        y = pick_year(year)
        states = report.state_summary(con, y)
        totals = {"premium": sum(r["earned_premium_cy"] or 0 for r in states),
                  "rebates": sum(r["rebates"] or 0 for r in states),
                  "owing": sum(r["insurers_owing"] for r in states)}
        return TEMPLATES.TemplateResponse(request, "dashboard.html", {
            "year": y, "years": years(), "states": states, "totals": totals, "counts": counts(y),
            "peers": report.peer_view(con, y, peer_company), "peer_company": peer_company})

    @app.get("/exceptions", response_class=HTMLResponse)
    def exceptions_page(request: Request, year: int | None = None, status: str | None = None,
                        category: str | None = None):
        y = pick_year(year)
        return TEMPLATES.TemplateResponse(request, "exceptions.html", {
            "year": y, "years": years(), "rows": report.exceptions(con, y, status or None, category or None),
            "status": status, "category": category, "counts": counts(y), "transitions": recon.TRANSITIONS})

    @app.post("/exceptions/{exception_id}/status")
    def update_status(exception_id: int, to_status: str = Form(...), note: str = Form(""),
                      year: int = Form(...)):
        try:
            recon.set_status(con, exception_id, to_status, note or None)
        except KeyError:
            raise HTTPException(404, "exception not found") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return RedirectResponse(f"/exceptions?year={year}", status_code=303)

    @app.get("/api/exceptions/{exception_id}/history")
    def history(exception_id: int):
        return [dict(r) for r in con.execute("SELECT from_status, to_status, note, actor, at FROM exception_events "
                                             "WHERE exception_id = ? ORDER BY id", (exception_id,))]

    @app.get("/api/summary")
    def summary(year: int | None = None):
        y = pick_year(year)
        return {"reporting_year": y, **counts(y)}

    return app


def _sum(rows: list[sqlite3.Row], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + r["n"]
    return out
