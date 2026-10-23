from app.parser import parse_text

def test_parser_preserves_table_like_rows_in_body():
    nodes = parse_text("Manual Title\n2.1 General Specifications\nParameter\nValue\nPressure range\n0-299 mmHg")
    section = next(n for n in nodes if n.heading == "2.1 General Specifications")
    assert "Pressure range" in section.body_text
    assert "0-299 mmHg" in section.body_text
