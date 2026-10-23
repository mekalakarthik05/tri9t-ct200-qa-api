from app.parser import parse_text, content_hash

def test_duplicate_heading_keeps_distinct_nodes_and_parents():
    text = "Manual Title\n1. Device\n1.1 Status\nStatus detail\n2. Device\n2.1 Status\nOther detail"
    nodes = parse_text(text)
    matches = [n for n in nodes if n.heading.endswith("Status")]
    assert len(matches) == 2
    assert matches[0] is not matches[1]
    assert matches[0].parent_index != matches[1].parent_index
    assert nodes[matches[0].parent_index].heading == "1. Device"
    assert nodes[matches[1].parent_index].heading == "2. Device"

def test_out_of_order_sections_keep_encounter_order_and_parent():
    nodes = parse_text("Manual Title\n3. Device Operation\n3.4 Auto Shutoff\nTimeout details\n3.3 Result Display\nDisplay details")
    headings = [n.heading for n in nodes]
    assert headings.index("3.4 Auto Shutoff") < headings.index("3.3 Result Display")
    assert next(n for n in nodes if n.heading == "3.4 Auto Shutoff").parent_index == 1
    assert next(n for n in nodes if n.heading == "3.3 Result Display").parent_index == 1

def test_missing_numbered_parent_is_flagged_not_silently_discarded():
    nodes = parse_text("Manual Title\n2.1 General Specifications\n2.1.1.1 Battery Life Under Typical Use\nBattery details")
    battery = next(n for n in nodes if "Battery Life" in n.heading)
    assert "missing_numbered_parent" in battery.warnings
    assert battery.parent_index is not None

def test_content_hash_changes_when_body_changes():
    assert content_hash("Battery", "250 cycles") != content_hash("Battery", "300 cycles")

def test_numbered_classification_list_stays_inside_result_section():
    nodes = parse_text("Manual Title\n3.3 Result Display and Classification\nAfter measurement the device displays values.\n1. Normal: systolic < 120 and diastolic < 80\n2. Elevated: systolic 120-129 and diastolic < 80")
    assert len([n for n in nodes if n.number == "1"]) == 0
    section = next(n for n in nodes if n.heading == "3.3 Result Display and Classification")
    assert "1. Normal" in section.body_text
    assert "2. Elevated" in section.body_text


def test_numbered_list_items_with_colon_never_become_headings():
    nodes = parse_text("Manual Title\n3.3 Result Display and Classification\n1. Measure cuff pressure after inflation\n2. Record final readings\n3. Warning: ensure cuff is secure")
    section = next(n for n in nodes if n.heading == "3.3 Result Display and Classification")
    assert [n for n in nodes if n.number == "1"] == []
    assert "1. Measure cuff pressure after inflation" in section.body_text
    assert "3. Warning: ensure cuff is secure" in section.body_text


def test_heading_after_numbered_list_item_is_not_swallowed():
    nodes = parse_text("Manual Title\n3.3 Result Display and Classification\n1. Measure cuff pressure\n4. Regulatory Information\nRegulatory details")
    assert any(n.heading == "4. Regulatory Information" for n in nodes)
