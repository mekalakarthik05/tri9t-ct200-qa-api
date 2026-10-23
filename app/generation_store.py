import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from .config import GENERATIONS_DIR

class GenerationStore:
    """Small JSON document store for immutable generated artifacts; replaceable with MongoDB."""
    def __init__(self, directory: Path | None = None):
        self.directory = directory or GENERATIONS_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def _read(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Unable to read generation artifact {path.name}") from exc

    def all(self):
        return [self._read(path) for path in sorted(self.directory.glob("*.json"))]

    def get(self, generation_id):
        p = self.directory / f"{generation_id}.json"
        return self._read(p) if p.exists() else None

    def save(self, payload):
        payload = dict(payload)
        payload.setdefault("generation_id", str(uuid.uuid4()))
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        p = self.directory / f"{payload['generation_id']}.json"
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload
