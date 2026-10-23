# Approach Document — CT-200 Traceable QA API

## 1. Goal and constraints

The service converts the supplied CT-200 PDF into a browsable, versioned tree; allows users to select version-pinned sections; generates structured QA test ideas; and reports whether the source text has changed since generation. The parser is intentionally CT-200-specific. It must prefer a visible warning to silently inventing hierarchy.

## 2. Parsing approach

PyMuPDF extracts the embedded PDF text and page reading order. The supplied files expose a usable text layer, so applying OCR to every page would introduce avoidable recognition errors. The pipeline checks for pages with very little extracted text and attempts Tesseract OCR only on those pages. OCR failure is surfaced as a warning. NFKC normalization handles ligatures and whitespace, while preserving the heading's original visible wording as much as possible.

The parser recognizes numbered headings such as `3. Device Operation` and `3.2 Cuff Inflation Sequence`. A child is attached to the closest preceding section-number prefix that exists. The document title is a root node. Nodes retain encounter order; numbering is not sorted because the source has 3.4 before 3.3. Skipped hierarchy levels are preserved and flagged (`missing_numbered_parent`) rather than silently dropped. Duplicate headings are separate occurrences; the version matcher consumes previous-version candidates one-to-one.

### Observed structural risks in the supplied PDF

- The battery subsection is numbered `2.1.1.1`, with intermediate levels absent.
- Section 3.4 appears before 3.3 in reading order.
- Paragraphs continue across page boundaries (for example, operating instructions and regulatory text).
- Tables (specifications and error codes) may be flattened into reading-order text.
- List items under result classification resemble numbered headings superficially. The parser retains the known classification labels and imperative-style entries as body text, but other unrecognized numbered lists could still be misclassified; this ambiguity needs regression coverage and manual review.
- PDF typography uses ligatures and unusual hyphenation; normalization is needed for stable matching and hashes.
- V2 has an additional page and new data-export content; added material should be represented as new nodes, not as edits to unrelated sections.
- V1 → V2 changes the battery estimate from 300 to 250 cycles and the low-battery threshold from 15% to 10%; inflation increments change from 40 mmHg to 30 mmHg; E3 auto-deflation changes from 2 seconds to 1.5 seconds; E6 and Section 5.3 Data Export are added.

### Known parser limitations and validation

The implementation retains table-like content as body text but does not reconstruct reliable cell geometry. This is explicit rather than pretending a flattened table is structurally perfect. Validation combines unit tests, inspection of extracted page text, and version-to-version checks. Further work should compare every parsed page with rendered page images and use PyMuPDF block coordinates for table/layout recovery. The tests cover duplicate headings, out-of-order headings, skipped hierarchy levels, numbered list items, changed hashes, and table-like rows.

## 3. Data model

- `Document`: stable document identity.
- `DocumentVersion`: immutable ingestion record with source filename and SHA-256 of the PDF.
- `LogicalNode`: cross-version identity.
- `NodeVersion`: immutable heading/body/parent/level/hash record for one document version.
- `Selection`: named set of exact node-version IDs plus snapshot text and hashes.
- Generated JSON artifact: selection ID, source version, exact source-node snapshots, hashes, model output and timestamp.

SQLite stores document/version/tree/selection relationships. A JSON directory is used as the justified local document store for generated LLM output; it is a small no-dependency substitute for MongoDB and can be migrated to a Mongo collection. The directory store is not designed for concurrent multi-worker production writes.

## 4. Version matching strategy

The matcher normalizes section numbers away from heading text for comparison, then matches by normalized heading and parent logical identity. Candidate nodes are consumed one-to-one, which prevents two repeated headings from collapsing onto a single old node. If the parent match fails, a normalized-heading fallback can preserve identity through some hierarchy shifts.

This strategy works well when headings remain stable and sections stay under the same parent. It breaks or becomes ambiguous when headings are renamed, identical siblings exist under the same parent, or a section moves. A production-grade matcher should combine path, text similarity, sibling order, and explicit ambiguity scores, and should leave uncertain matches unresolved for human review rather than force a match.

## 5. Hashes and staleness

A SHA-256 hash is computed from normalized heading and body text. Exact equality means the stored source text is unchanged under this normalization; a different hash means content changed. At generation retrieval, every source logical node is resolved against the latest version and marked `unchanged`, `changed`, or `removed`. The API includes source/current node IDs and hashes and an explicit `not_automatically_assessed` note for changed content.

Hash comparison does not decide whether a change is safety-significant. A punctuation change and a pressure threshold change both trigger `changed`; the service does not label either clinically safe or unsafe. A next iteration could extract changed numeric values/units and rule keywords for triage, but such impact heuristics must be validated and remain advisory.

## 6. LLM prompt and failure policy

The prompt asks for 3–5 concrete test ideas grounded only in the pinned source, with title, objective, preconditions, steps, expected result, source node IDs and risk level. Groq's JSON response mode is supported when configured; deterministic mock generation is the default so the whole flow can be tested without secrets or network access.

Pydantic validates the response shape, field lengths, list minimums, case count and risk-level enum. Every cited source ID must belong to the pinned selection. Invalid JSON or schema output is rejected and not stored; provider errors return an API error. The current implementation fails closed rather than attempting a second repair prompt. This is easy to reason about and avoids storing malformed output, though a bounded retry with an error-specific repair prompt could improve availability.

There is no automatic retry or repair attempt: each request makes at most one provider call and one validation attempt. Only `mock` and `groq` are supported provider settings; an unknown `LLM_PROVIDER` value is rejected explicitly rather than falling through to mock generation.

Repeated requests for the same selection return the existing generation by default (idempotent behavior). `force_new=true` creates another generation. This avoids unexpected duplicate provider charges while allowing explicit regeneration.

## 7. API surface

- `POST /documents/ingest`: ingest uploaded PDF as the next version.
- `POST /demo/ingest-bundled`: local convenience route for supplied files.
- `GET /documents/{document_id}/sections`: list sections by version (latest by default).
- `GET /nodes/{node_id}`: node, full text, hash and descendants.
- `GET /nodes/search`: heading/body search.
- `GET /nodes/{logical_node_id}/changes`: per-version hash history and lightweight diff summary.
- `POST /selections`, `GET /selections/{selection_id}`: create/read version-pinned selection.
- `POST /generations`: generate test ideas.
- `GET /generations?selection_id=...` or `?node_id=...`: retrieve generated cases with current staleness status.

## 8. Decision log

1. **Most likely silent failure:** a heading or body block can be assigned to the wrong parent while still producing valid JSON. I would catch this with rendered-page visual review, section-number/parent invariants, and regression fixtures for the known 2.1.1.1 and 3.4/3.3 cases.
2. **Simplicity over correctness:** the version matcher uses normalized headings and parent identity rather than a semantic matcher with confidence thresholds. A moved or renamed section, or repeated headings under the same parent, could be mis-matched first. Ambiguous matches should be surfaced for review in a production implementation.
3. **Unsupported input:** a complex multi-column table with no reliable text layer may be flattened or OCRed in the wrong order. The current implementation retains extracted text and emits OCR warnings when extraction fails; it does not claim reliable cell reconstruction. Such pages should be marked for manual review.

## 9. What I would improve with more time

- Coordinate-aware table and multi-column extraction, with page image overlays for audit.
- Persist parser warnings and confidence scores per block, not only per node.
- A version matcher with candidate scores and an `unresolved` state.
- Bounded LLM retry/repair and provider/model/prompt version metadata.
- Transactional, atomic artifact writes or MongoDB for concurrent generation requests.
- Numeric/unit change detection to help reviewers prioritize impact without automating safety conclusions.
- Broader integration tests exercising v1 ingest → selection → generation → v2 ingest → stale retrieval.
