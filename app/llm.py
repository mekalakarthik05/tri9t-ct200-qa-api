import json, os, re
import httpx
from .schemas import TestCaseSet

SYSTEM_PROMPT = """You are a QA engineer for a fictional home blood pressure monitor. Generate 3 to 5 concrete, repeatable software/device QA test ideas ONLY from supplied source text. Do not invent requirements or claim medical validation. Each test must include title, objective, preconditions (array), steps (array), expected_result, source_node_ids (array containing IDs supplied), and risk_level (low/medium/high). For changed numerical limits, use the exact value in the provided source. Return JSON only with top-level key test_cases."""

def _mock(text, node_ids):
    # Deterministic local mode enables an end-to-end demo without credentials.
    excerpt = text[:500]
    cases = []
    templates = [
        ("Verify normal operation path", "Confirm the selected requirement is followed during a normal scenario", "Perform the documented operation using nominal conditions", "The device follows the behavior stated in the selected source text", "medium"),
        ("Verify boundary condition", "Check behavior at the documented limit", "Set up a controlled test at the exact boundary stated in the source", "Observed behavior matches the documented boundary and does not exceed it", "high"),
        ("Verify invalid or failure condition", "Confirm the documented error/failure path", "Simulate the documented failure condition and observe the device response", "The expected error handling and user-visible response match the source text", "high"),
        ("Verify recovery behavior", "Confirm the device remains in the documented state after the scenario", "Repeat the scenario and follow the documented recovery instructions", "The device returns to the documented state without losing required traceability", "medium"),
    ]
    for title, obj, step, expected, risk in templates:
        cases.append({"title": title, "objective": obj + ". Source excerpt: " + excerpt[:100], "preconditions": ["Test device or simulator is available", "Selected source requirement is loaded"], "steps": ["Record the current firmware and test setup", step, "Record displayed status and timing"], "expected_result": expected, "source_node_ids": node_ids[:], "risk_level": risk})
    return {"test_cases": cases}

def generate_cases(text: str, node_ids: list[str]) -> TestCaseSet:
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider not in {"mock", "groq"}:
        raise ValueError(
            f"Unsupported LLM_PROVIDER {provider!r}; expected 'mock' or 'groq'"
        )
    raw = None
    if provider == "groq":
        key = os.getenv("GROQ_API_KEY")
        if not key: raise RuntimeError("LLM_PROVIDER=groq but GROQ_API_KEY is not configured")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        payload = {"model": model, "temperature": 0.1, "response_format": {"type": "json_object"}, "messages": [{"role":"system","content":SYSTEM_PROMPT}, {"role":"user","content":json.dumps({"source_node_ids":node_ids,"source_text":text})}]}
        response = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization":f"Bearer {key}"}, json=payload, timeout=45)
        response.raise_for_status(); raw = response.json()["choices"][0]["message"]["content"]
    else:
        raw = json.dumps(_mock(text, node_ids))
    # Bounded repair/validation policy: one parse/validation attempt; no malformed data is persisted.
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("LLM returned malformed JSON; generation was not stored") from exc
    validated = TestCaseSet.model_validate(data)
    allowed = set(node_ids)
    for case in validated.test_cases:
        if not set(case.source_node_ids).issubset(allowed):
            raise ValueError("LLM referenced a source node outside the pinned selection")
    return validated
