"""CT-200-specific PDF parser. Text extraction first; OCR fallback is intentionally explicit."""
import hashlib, re, unicodedata
from pathlib import Path
import pymupdf as fitz

HEADING = re.compile(r"^(?P<num>\d+(?:\.\d+)*)(?:\.)?\s+(?P<title>.+?)\s*$")
KNOWN_UNNUMBERED = {"CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual"}

class ParsedNode:
    def __init__(self, heading, number, level, body_text="", parent_index=None, ordinal=0, warnings=None):
        self.heading, self.number, self.level = heading, number, level
        self.body_text, self.parent_index, self.ordinal = body_text.strip(), parent_index, ordinal
        self.warnings = warnings or []
    def as_dict(self):
        return {"heading": self.heading, "number": self.number, "level": self.level,
                "body_text": self.body_text, "parent_index": self.parent_index,
                "ordinal": self.ordinal, "warnings": self.warnings,
                "content_hash": content_hash(self.heading, self.body_text)}

def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).replace("\u00ad", "")
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl")
    s = re.sub(r"[\t ]+", " ", s)
    return s.strip()

def content_hash(heading: str, body: str) -> str:
    canonical = normalize_text(heading).casefold() + "\n" + normalize_text(body).casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def extract_pdf(path: str | Path) -> tuple[str, str]:
    path = Path(path)
    doc = fitz.open(path)
    pages, warnings = [], []
    for i, page in enumerate(doc):
        text = page.get_text("text", sort=True).strip()
        if len(text) < 30:
            # OCR is not silently assumed available; caller receives an actionable warning.
            try:
                import pytesseract
                from PIL import Image
                import io
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                text = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png")))).strip()
                if not text: warnings.append(f"Page {i+1}: OCR returned no text")
            except Exception as exc:
                warnings.append(f"Page {i+1}: text layer absent and OCR unavailable/failed ({type(exc).__name__})")
        pages.append(text)
    return "\n".join(pages), "\n".join(warnings)

def _looks_like_numbered_list_item(line: str) -> bool:
    match = HEADING.match(line)
    if not match:
        return False
    title = match.group("title")
    if re.match(r"^(Measure|Record|Check|Ensure|Verify|Set|Place|Press|Connect|Disconnect|Inspect|Use|Rotate|Insert|Remove|Power|Apply|Wait|Observe|Read|Review|Warning|Caution|Select|Follow|Perform|Adjust|Hold|Turn|Start|Stop|Clean|Store|Attach|Detach|Enter|Press|Release)\b", title, re.I):
        return True
    return bool(re.match(r"^\d+\.\s+(Normal:|Elevated:|Hypertension Stage|Hypertensive Crisis:)", line, re.I))


def parse_text(text: str) -> list[ParsedNode]:
    """Reconstruct numbered hierarchy while preserving encounter order and duplicate titles."""
    lines = [normalize_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    nodes: list[ParsedNode] = []
    current = None
    title_lines = []
    for line in lines:
        # The PDF title is wrapped over multiple lines; keep as a root node.
        if not nodes and (line.startswith("CardioTrack CT-200") or line == "User Manual"):
            title_lines.append(line)
            continue
        if _looks_like_numbered_list_item(line):
            if current is not None:
                nodes[current].body_text += ("\n" if nodes[current].body_text else "") + line
            else:
                title_lines.append(line)
            continue
        match = HEADING.match(line)
        if match:
            number, heading = match.group("num"), match.group("title")
            depth = number.count(".") + 1
            warnings = []
            # A section number can skip a level (e.g. 2.1.1.1); preserve it and flag it.
            if depth > 1 and not any(n.number == ".".join(number.split(".")[:-1]) for n in nodes):
                warnings.append("missing_numbered_parent")
            # parent is nearest preceding numbered prefix, not the previous heading.
            parent_index = None
            parts = number.split(".")
            for cut in range(len(parts)-1, 0, -1):
                prefix = ".".join(parts[:cut])
                found = next((i for i in range(len(nodes)-1, -1, -1) if nodes[i].number == prefix), None)
                if found is not None:
                    parent_index = found; break
            if parent_index is None and depth > 1:
                warnings.append("attached_to_nearest_existing_ancestor_or_root")
            node = ParsedNode(line, number, depth, "", parent_index, len(nodes), warnings)
            nodes.append(node); current = len(nodes)-1
            continue
        # Recognize numbered list items as body, not section headings.
        if current is not None:
            nodes[current].body_text += ("\n" if nodes[current].body_text else "") + line
        else:
            title_lines.append(line)
    # Add a title/root if a title was present; all top-level numbered sections are children.
    if title_lines:
        title = " ".join(title_lines[:3]).strip()
        root = ParsedNode(title, "ROOT", 0, "", None, 0, [])
        nodes = [root] + nodes
        for n in nodes[1:]:
            n.ordinal += 1
            if n.parent_index is not None: n.parent_index += 1
            else: n.parent_index = 0
    # Recalculate body text hash later; headings remain literal, including numbering.
    return nodes

def parse_pdf(path: str | Path) -> tuple[list[ParsedNode], str, str]:
    text, extraction_warnings = extract_pdf(path)
    return parse_text(text), text, extraction_warnings
