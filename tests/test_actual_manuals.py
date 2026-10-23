from pathlib import Path
from app.parser import parse_pdf, content_hash

DATA = Path(__file__).resolve().parents[1] / "data"

def test_supplied_v1_v2_capture_known_requirement_changes():
    v1, _, _ = parse_pdf(DATA / "ct200_manual.pdf")
    v2, _, _ = parse_pdf(DATA / "ct200_manual_v2.pdf")
    battery1 = next(n for n in v1 if "Battery Life Under Typical Use" in n.heading)
    battery2 = next(n for n in v2 if "Battery Life Under Typical Use" in n.heading)
    inflation1 = next(n for n in v1 if "Cuff Inflation Sequence" in n.heading or "Cuff Inflation Sequence" in n.heading.replace("Cuﬀ", "Cuff"))
    inflation2 = next(n for n in v2 if "Cuff Inflation Sequence" in n.heading or "Cuff Inflation Sequence" in n.heading.replace("Cuﬀ", "Cuff"))
    assert "300" in battery1.body_text and "15%" in battery1.body_text
    assert "250" in battery2.body_text and "10%" in battery2.body_text
    assert content_hash(battery1.heading, battery1.body_text) != content_hash(battery2.heading, battery2.body_text)
    assert "40 mmHg increments" in inflation1.body_text
    assert "30 mmHg increments" in inflation2.body_text
    assert any("Data Export" in n.heading for n in v2)
    assert not any("Data Export" in n.heading for n in v1)
