from pydantic import BaseModel, Field, ConfigDict
from typing import Literal

class IngestResponse(BaseModel):
    document_id: str
    version: int
    nodes_created: int
    nodes_matched: int
    warnings: list[str] = []

class SelectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    node_ids: list[str] = Field(min_length=1)
    version: int | None = None

class GenerationRequest(BaseModel):
    selection_id: str
    force_new: bool = False

class TestCase(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    objective: str = Field(min_length=5)
    preconditions: list[str] = Field(min_length=1)
    steps: list[str] = Field(min_length=2)
    expected_result: str = Field(min_length=5)
    source_node_ids: list[str] = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"]

class TestCaseSet(BaseModel):
    test_cases: list[TestCase] = Field(min_length=3, max_length=5)

class GenerationOut(BaseModel):
    generation_id: str
    selection_id: str
    created_at: str
    source_version: int
    test_cases: list[TestCase]
    staleness: list[dict]
