"""Repeatable end-to-end v1 -> selection -> generation -> v2 -> staleness demo."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="ct200-demo-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP.name) / 'demo.db'}"
os.environ["GENERATIONS_DIR"] = str(Path(TEMP.name) / "generated")
os.environ["LLM_PROVIDER"] = "mock"

client = None
try:
    # Import after setting environment variables so the app uses the isolated demo DB.
    from fastapi.testclient import TestClient
    from app.main import app
    from app.db import engine

    def upload(filename):
        path = ROOT / "data" / filename
        with path.open("rb") as f:
            response = client.post("/documents/ingest", files={"file": (filename, f, "application/pdf")})
        response.raise_for_status()
        return response.json()

    with TestClient(app) as test_client:
        client = test_client
        v1 = upload("ct200_manual.pdf")
        v2same = upload("ct200_manual.pdf")  # idempotency check
        search = client.get("/nodes/search", params={"q": "Battery Life", "version": 1}).json()
        node = next(n for n in search["results"] if "Battery Life" in n["heading"])
        selection = client.post("/selections", json={"name": "Battery life requirement", "version": 1, "node_ids": [node["node_id"]]}).json()
        generation = client.post("/generations", json={"selection_id": selection["selection_id"]}).json()
        v2 = upload("ct200_manual_v2.pdf")
        retrieved = client.get("/generations", params={"selection_id": selection["selection_id"]}).json()
        statuses = [s["status"] for g in retrieved["generations"] for s in g["staleness"]]
        assert v1["version"] == 1 and v2same["version"] == 1 and v2["version"] == 2
        assert len(generation["test_cases"]) in range(3, 6)
        assert "changed" in statuses, f"Expected changed source status, got {statuses}"
        print({"v1": v1, "same_file_reingest_version": v2same["version"], "selection_id": selection["selection_id"],
               "generated_cases": len(generation["test_cases"]), "v2": v2,
               "retrieval_staleness": statuses, "result": "PASS"})
finally:
    # TestClient context manager closes the client. Dispose any partially imported DB engine
    # too, so failed startup does not leave SQLite file handles locked on Windows.
    db_module = sys.modules.get("app.db")
    if db_module is not None:
        try:
            db_module.engine.dispose(close=True)
        except Exception:
            pass
    TEMP.cleanup()
