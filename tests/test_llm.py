import json
from unittest.mock import Mock

import pytest

from app import llm


def test_groq_provider_sends_configured_bearer_token(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-api-key")
    response = Mock()
    response.json.return_value = {
        "choices": [
            {"message": {"content": json.dumps(llm._mock("source text", ["node-1"]))}}
        ]
    }
    request = Mock(return_value=response)
    monkeypatch.setattr(llm.httpx, "post", request)

    result = llm.generate_cases("source text", ["node-1"])

    assert result.test_cases
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer test-api-key"


def test_unknown_provider_does_not_fall_back_to_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "typo-provider")

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        llm.generate_cases("source text", ["node-1"])
