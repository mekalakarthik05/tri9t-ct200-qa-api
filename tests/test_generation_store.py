import pytest

from app.generation_store import GenerationStore


def test_corrupt_generation_artifact_is_reported(tmp_path):
    (tmp_path / "broken.json").write_text("{invalid", encoding="utf-8")
    store = GenerationStore(tmp_path)

    with pytest.raises(RuntimeError, match="broken.json"):
        store.all()
