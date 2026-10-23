import hashlib, json, re, uuid
from pathlib import Path
from difflib import SequenceMatcher
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import select
from .db import Base, engine, get_db
from .models import Document, DocumentVersion, LogicalNode, NodeVersion, Selection
from .parser import parse_pdf, parse_text, content_hash
from .schemas import IngestResponse, SelectionCreate, GenerationRequest
from .generation_store import GenerationStore
from .llm import generate_cases

Base.metadata.create_all(bind=engine)
app = FastAPI(title="CT-200 Traceable QA API", version="1.0.0", description="Versioned document hierarchy and traceable QA generation for the CT-200 manual.")
store = GenerationStore()
DOC_ID = "ct200-manual"

def source_hash(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(65536),b""): h.update(chunk)
    return h.hexdigest()

def normalize_heading(s):
    s = re.sub(r"^\d+(?:\.\d+)*\.\s*", "", s.strip().casefold())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def ingest_path(path: Path, filename: str, db: Session):
    pdf_nodes, raw_text, extraction_warnings = parse_pdf(path)
    doc = db.get(Document, DOC_ID)
    if doc is None:
        doc = Document(id=DOC_ID, title="CardioTrack CT-200 Home Blood Pressure Monitor")
        db.add(doc); db.flush()
    digest = source_hash(path)
    existing = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==DOC_ID, DocumentVersion.source_sha256==digest))
    if existing:
        return {"document_id": DOC_ID, "version": existing.version_number, "nodes_created": 0, "nodes_matched": len(existing.nodes), "warnings":["Identical PDF already ingested; existing version returned."]}
    version_number = (db.scalar(select(DocumentVersion.version_number).where(DocumentVersion.document_id==DOC_ID).order_by(DocumentVersion.version_number.desc()).limit(1)) or 0)+1
    ver = DocumentVersion(document_id=DOC_ID, version_number=version_number, source_filename=filename, source_sha256=digest)
    db.add(ver); db.flush()
    prev_ver = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==DOC_ID, DocumentVersion.version_number==version_number-1))
    prev_nodes = list(prev_ver.nodes) if prev_ver else []
    # Match by normalized heading + parent logical identity; duplicate headings are consumed one-to-one in order.
    matched, used_prev = {}, set()
    def logical_parent_key(parsed, index):
        p = parsed[index].parent_index
        return matched.get(p) if p is not None else None
    created = 0
    new_records = []
    for i, pnode in enumerate(pdf_nodes):
        parent_logical = logical_parent_key(pdf_nodes, i)
        candidates = [n for n in prev_nodes if n.id not in used_prev and normalize_heading(n.heading)==normalize_heading(pnode.heading) and (db.get(NodeVersion,n.parent_node_id).logical_node_id if n.parent_node_id and db.get(NodeVersion,n.parent_node_id) else None)==parent_logical]
        if not candidates:
            # Root and headings can shift slightly; only allow same normalized heading as a fallback.
            candidates = [n for n in prev_nodes if n.id not in used_prev and normalize_heading(n.heading)==normalize_heading(pnode.heading)]
        old = candidates[0] if candidates else None
        if old:
            logical_id = old.logical_node_id; used_prev.add(old.id)
        else:
            logical_id = str(uuid.uuid4()); db.add(LogicalNode(id=logical_id, document_id=DOC_ID)); created += 1
        matched[i] = logical_id
        new_records.append((i,pnode,logical_id))
    # Create node-version records in encounter order; parent references resolve to new version IDs.
    version_node_ids = {}
    for i,pnode,logical_id in new_records:
        node_id = str(uuid.uuid4()); version_node_ids[i] = node_id
        parent_id = version_node_ids.get(pnode.parent_index) if pnode.parent_index is not None else None
        db.add(NodeVersion(id=node_id, logical_node_id=logical_id, version_id=ver.id, parent_node_id=parent_id,
            heading=pnode.heading, level=pnode.level, body_text=pnode.body_text,
            content_hash=content_hash(pnode.heading,pnode.body_text), ordinal=pnode.ordinal, structure_warnings=pnode.warnings))
    db.commit()
    warnings = [x for x in extraction_warnings.splitlines() if x]
    warnings.extend(f"{p.heading}: {', '.join(p.warnings)}" for p in pdf_nodes if p.warnings)
    return {"document_id":DOC_ID,"version":version_number,"nodes_created":created,"nodes_matched":len(pdf_nodes)-created,"warnings":warnings}

@app.get("/health")
def health(): return {"status":"ok"}

@app.post("/documents/ingest", response_model=IngestResponse)
def ingest(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"): raise HTTPException(400,"Upload a PDF file")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(file.file.read()); path=Path(tmp.name)
    try: return ingest_path(path,file.filename,db)
    finally: path.unlink(missing_ok=True)

@app.get("/documents/{document_id}/sections")
def list_sections(document_id: str, version: int | None = None, db: Session = Depends(get_db)):
    versions = list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==document_id).order_by(DocumentVersion.version_number.desc())))
    if not versions: raise HTTPException(404,"Document not found; ingest a PDF first")
    selected = next((v for v in versions if v.version_number==version), None) if version else versions[0]
    if selected is None: raise HTTPException(404,"Version not found")
    nodes = list(db.scalars(select(NodeVersion).where(NodeVersion.version_id==selected.id).order_by(NodeVersion.ordinal)))
    return {"document_id":document_id,"version":selected.version_number,"sections":[node_out(n) for n in nodes if n.level==1]}

def node_out(n):
    return {"node_id":n.id,"logical_node_id":n.logical_node_id,"heading":n.heading,"level":n.level,"parent_node_id":n.parent_node_id,"body_text":n.body_text,"content_hash":n.content_hash,"ordinal":n.ordinal,"warnings":n.structure_warnings}

@app.get("/nodes/search")
def search_nodes(q: str = Query(min_length=1), version: int | None = None, db: Session = Depends(get_db)):
    versions = list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==DOC_ID).order_by(DocumentVersion.version_number.desc())))
    if not versions: raise HTTPException(404,"Ingest a document first")
    v = next((x for x in versions if x.version_number==version),None) if version else versions[0]
    if v is None: raise HTTPException(404,"Version not found")
    needle=q.casefold()
    nodes=list(db.scalars(select(NodeVersion).where(NodeVersion.version_id==v.id).order_by(NodeVersion.ordinal)))
    return {"version":v.version_number,"query":q,"results":[node_out(n) for n in nodes if needle in n.heading.casefold() or needle in n.body_text.casefold()]}

@app.get("/nodes/{node_id}")
def get_node(node_id: str, db: Session = Depends(get_db)):
    n=db.get(NodeVersion,node_id)
    if not n: raise HTTPException(404,"Node version not found")
    children=list(db.scalars(select(NodeVersion).where(NodeVersion.parent_node_id==n.id).order_by(NodeVersion.ordinal)))
    # Include descendant text to provide a full selected subtree without losing direct node text.
    def descendants(node):
        kids=list(db.scalars(select(NodeVersion).where(NodeVersion.parent_node_id==node.id).order_by(NodeVersion.ordinal)))
        return [dict(node_out(k), children=descendants(k)) for k in kids]
    def flatten(node):
        parts=[node.heading, node.body_text]
        for child in db.scalars(select(NodeVersion).where(NodeVersion.parent_node_id==node.id).order_by(NodeVersion.ordinal)):
            parts.append(flatten(child))
        return "\n".join(part for part in parts if part)
    return dict(node_out(n), children=descendants(n), full_text=flatten(n))

@app.get("/nodes/{logical_node_id}/changes")
def node_changes(logical_node_id: str, db: Session=Depends(get_db)):
    rows=list(db.scalars(select(NodeVersion).where(NodeVersion.logical_node_id==logical_node_id)))
    rows.sort(key=lambda n: db.get(DocumentVersion,n.version_id).version_number)
    if not rows: raise HTTPException(404,"Logical node not found")
    out=[]
    for i,n in enumerate(rows):
        version=db.get(DocumentVersion,n.version_id).version_number
        previous=rows[i-1] if i else None
        status="new" if previous is None else ("unchanged" if previous.content_hash==n.content_hash else "changed")
        diff=None if previous is None or status=="unchanged" else {"previous_heading":previous.heading,"current_heading":n.heading,"previous_chars":len(previous.body_text),"current_chars":len(n.body_text),"similarity":round(SequenceMatcher(None,previous.body_text,n.body_text).ratio(),3),"previous_excerpt":previous.body_text[:180],"current_excerpt":n.body_text[:180]}
        out.append({"version":version,"node_id":n.id,"status":status,"content_hash":n.content_hash,"diff":diff})
    return {"logical_node_id":logical_node_id,"history":out}

@app.post("/selections")
def create_selection(payload: SelectionCreate, db: Session=Depends(get_db)):
    versions=list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id==DOC_ID).order_by(DocumentVersion.version_number.desc())))
    if not versions: raise HTTPException(404,"Ingest a document first")
    v=next((x for x in versions if x.version_number==payload.version),None) if payload.version else versions[0]
    if v is None: raise HTTPException(404,"Version not found")
    selected=[]
    for node_id in payload.node_ids:
        n=db.get(NodeVersion,node_id)
        if not n or n.version_id!=v.id: raise HTTPException(400,f"Node {node_id} does not belong to pinned version {v.version_number}")
        selected.append({"node_id":n.id,"logical_node_id":n.logical_node_id,"content_hash":n.content_hash,"heading":n.heading,"body_text":n.body_text})
    selection=Selection(id=str(uuid.uuid4()),name=payload.name,document_id=DOC_ID,version_number=v.version_number,items=selected)
    db.add(selection); db.commit()
    return {"selection_id":selection.id,"name":selection.name,"version":selection.version_number,"items":selection.items}

@app.post("/generations")
def create_generation(payload: GenerationRequest, db: Session=Depends(get_db)):
    selection=db.get(Selection,payload.selection_id)
    if not selection: raise HTTPException(404,"Selection not found")
    # Idempotency: same selection returns existing artifact unless force_new=true.
    if not payload.force_new:
        existing=next((g for g in store.all() if g.get("selection_id")==selection.id),None)
        if existing: return with_staleness(existing,db)
    source_text="\n\n".join(x["heading"]+"\n"+x["body_text"] for x in selection.items)
    try: cases=generate_cases(source_text,[x["node_id"] for x in selection.items])
    except Exception as exc: raise HTTPException(502,f"Generation failed validation/provider call: {str(exc)}")
    payload_out={"selection_id":selection.id,"selection_name":selection.name,"document_id":selection.document_id,"source_version":selection.version_number,
        "source_nodes":selection.items,"source_hashes":{x["node_id"]:x["content_hash"] for x in selection.items},"test_cases":[c.model_dump() for c in cases.test_cases]}
    saved=store.save(payload_out)
    return with_staleness(saved,db)

def with_staleness(g,db):
    current_version=db.scalar(select(DocumentVersion).where(DocumentVersion.document_id==g["document_id"]).order_by(DocumentVersion.version_number.desc()))
    results=[]
    for source in g.get("source_nodes",[]):
        rows=list(db.scalars(select(NodeVersion).where(NodeVersion.logical_node_id==source["logical_node_id"])))
        current=next((n for n in rows if current_version and n.version_id==current_version.id),None)
        if current is None: status="removed"
        elif current.content_hash==source["content_hash"]: status="unchanged"
        else: status="changed"
        results.append({"source_node_id":source["node_id"],"logical_node_id":source["logical_node_id"],"source_version":g["source_version"],"current_version":current_version.version_number if current_version else None,"status":status,"current_node_id":current.id if current else None,"current_hash":current.content_hash if current else None,"impact_assessment":"not_automatically_assessed" if status=="changed" else None})
    out=dict(g); out["staleness"]=results
    return out

@app.get("/generations")
def retrieve_generations(selection_id: str | None=None, node_id: str | None=None, db: Session=Depends(get_db)):
    if not selection_id and not node_id: raise HTTPException(400,"Provide selection_id or node_id")
    generations=store.all(); results=[]
    for g in generations:
        if selection_id and g.get("selection_id")!=selection_id: continue
        if node_id and not any(s.get("node_id")==node_id or s.get("logical_node_id")==node_id for s in g.get("source_nodes",[])): continue
        results.append(with_staleness(g,db))
    return {"count":len(results),"generations":results}

@app.get("/selections/{selection_id}")
def get_selection(selection_id: str, db: Session=Depends(get_db)):
    s=db.get(Selection,selection_id)
    if not s: raise HTTPException(404,"Selection not found")
    return {"selection_id":s.id,"name":s.name,"version":s.version_number,"items":s.items}

@app.post("/demo/ingest-bundled")
def ingest_bundled(db: Session=Depends(get_db)):
    """Convenience endpoint for local demo; expects PDFs in ./data."""
    base=Path("data")
    v1=base/"ct200_manual.pdf"; v2=base/"ct200_manual_v2.pdf"
    if not v1.exists() or not v2.exists(): raise HTTPException(404,"Place the provided PDFs in ./data")
    return {"v1":ingest_path(v1,v1.name,db),"v2":ingest_path(v2,v2.name,db)}
