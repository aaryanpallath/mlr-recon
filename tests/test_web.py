from fastapi.testclient import TestClient

from mlrrecon.db import connect, migrate
from mlrrecon.ingest import ingest_zip
from mlrrecon.recon import reconcile
from mlrrecon.web import create_app


def client(tmp_path, puf) -> tuple[TestClient, int]:
    db = tmp_path / "t.db"
    con = connect(db)
    migrate(con)
    ingest_zip(con, puf)
    reconcile(con, 2024)
    eid = con.execute("SELECT id FROM exceptions WHERE filing_id = 5").fetchone()[0]
    con.close()
    return TestClient(create_app(db, peer_company="Clean Large Group")), eid


def test_dashboard_and_exception_workflow(tmp_path, puf):
    c, eid = client(tmp_path, puf)
    page = c.get("/")
    assert page.status_code == 200 and "Clean Large Group" in page.text
    ex = c.get("/exceptions?year=2024&category=unexplained")
    assert ex.status_code == 200 and "Mystery Health" in ex.text and "Typo Insurance" not in ex.text
    assert c.get("/api/summary").json()["by_status"] == {"open": 3}
    r = c.post(f"/exceptions/{eid}/status", data={"to_status": "investigating", "note": "emailed", "year": 2024},
               follow_redirects=False)
    assert r.status_code == 303
    assert [h["to_status"] for h in c.get(f"/api/exceptions/{eid}/history").json()] == ["open", "investigating"]
    bad = c.post(f"/exceptions/{eid}/status", data={"to_status": "bogus", "year": 2024})
    assert bad.status_code == 400
    assert c.post("/exceptions/999/status", data={"to_status": "resolved", "year": 2024}).status_code == 404
