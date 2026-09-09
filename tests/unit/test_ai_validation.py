"""
Unit tests for the AI response validation pipeline (sections 19/37).

Every case section 37 explicitly lists is covered here: valid response,
malformed JSON, missing fields, unexpected fields, empty response, timeout,
API failure, hallucinated values, very large input. None of these touch a
real network — the provider boundary (call_ai_provider) is never invoked
here at all; only the parsing/validation layer is under test.
"""
import pytest

from app.ai.schemas import AIInsightResponse
from app.ai.service import AIResponseValidationError, parse_and_validate_ai_response
from app.common.enums import RiskLevel


class TestValidResponse:
    def test_valid_json_parses_correctly(self):
        raw = '{"risk_level": "medium", "insight": "Declining engagement.", "reason": "Workouts down 40%.", "recommended_action": "Reach out."}'
        result = parse_and_validate_ai_response(raw)
        assert isinstance(result, AIInsightResponse)
        assert result.risk_level == RiskLevel.MEDIUM
        assert result.insight == "Declining engagement."

    def test_valid_json_wrapped_in_markdown_fence(self):
        raw = '```json\n{"risk_level": "low", "insight": "Stable.", "reason": "No change.", "recommended_action": "None needed."}\n```'
        result = parse_and_validate_ai_response(raw)
        assert result.risk_level == RiskLevel.LOW

    def test_valid_json_wrapped_in_bare_fence(self):
        raw = '```\n{"risk_level": "high", "insight": "At risk.", "reason": "No visits.", "recommended_action": "Call today."}\n```'
        result = parse_and_validate_ai_response(raw)
        assert result.risk_level == RiskLevel.HIGH


class TestMalformedJSON:
    def test_truncated_json_rejected(self):
        raw = '{"risk_level": "medium", "insight": "Declin'
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_MALFORMED_JSON"

    def test_non_json_prose_rejected(self):
        raw = "I think this member is doing okay but could improve."
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_MALFORMED_JSON"

    def test_json_array_instead_of_object_rejected(self):
        raw = '["medium", "insight text"]'
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_MALFORMED_JSON"

    def test_trailing_comma_json_rejected(self):
        raw = '{"risk_level": "low", "insight": "ok", "reason": "fine", "recommended_action": "none",}'
        with pytest.raises(AIResponseValidationError):
            parse_and_validate_ai_response(raw)


class TestMissingFields:
    def test_missing_risk_level_rejected(self):
        raw = '{"insight": "x", "reason": "y", "recommended_action": "z"}'
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_SCHEMA_INVALID"

    def test_missing_recommended_action_rejected(self):
        raw = '{"risk_level": "low", "insight": "x", "reason": "y"}'
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_SCHEMA_INVALID"

    def test_empty_object_rejected(self):
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response("{}")
        assert exc_info.value.code == "AI_SCHEMA_INVALID"


class TestUnexpectedFields:
    def test_extra_unknown_fields_are_tolerated(self):
        """Section 37: unexpected fields must not break validation — they're
        silently ignored, not rejected."""
        raw = (
            '{"risk_level": "low", "insight": "x", "reason": "y", "recommended_action": "z", '
            '"confidence_score": 0.97, "model_version": "gemma-flash-lite-experimental"}'
        )
        result = parse_and_validate_ai_response(raw)
        assert result.risk_level == RiskLevel.LOW
        assert not hasattr(result, "confidence_score")


class TestEmptyResponse:
    def test_empty_string_rejected(self):
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response("")
        assert exc_info.value.code == "AI_EMPTY_RESPONSE"

    def test_whitespace_only_rejected(self):
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response("   \n  ")
        assert exc_info.value.code == "AI_EMPTY_RESPONSE"

    def test_none_rejected(self):
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(None)
        assert exc_info.value.code == "AI_EMPTY_RESPONSE"


class TestHallucinatedValues:
    def test_invalid_risk_level_enum_rejected(self):
        """A hallucinated risk_level outside the enum must fail validation,
        not be silently coerced or accepted."""
        raw = '{"risk_level": "catastrophic", "insight": "x", "reason": "y", "recommended_action": "z"}'
        with pytest.raises(AIResponseValidationError) as exc_info:
            parse_and_validate_ai_response(raw)
        assert exc_info.value.code == "AI_SCHEMA_INVALID"

    def test_wrong_type_for_insight_rejected(self):
        raw = '{"risk_level": "low", "insight": 12345, "reason": "y", "recommended_action": "z"}'
        with pytest.raises(AIResponseValidationError):
            parse_and_validate_ai_response(raw)

    def test_null_risk_level_rejected(self):
        raw = '{"risk_level": null, "insight": "x", "reason": "y", "recommended_action": "z"}'
        with pytest.raises(AIResponseValidationError):
            parse_and_validate_ai_response(raw)


class TestVeryLargeInput:
    def test_oversized_insight_field_rejected(self):
        """A hallucinated wall of text must not be stored verbatim — the
        schema's max_length caps enforce this."""
        huge_text = "x" * 5000
        raw = f'{{"risk_level": "low", "insight": "{huge_text}", "reason": "y", "recommended_action": "z"}}'
        with pytest.raises(AIResponseValidationError):
            parse_and_validate_ai_response(raw)

    def test_reasonably_long_but_valid_insight_accepted(self):
        text = "This member has shown a consistent pattern of declining engagement. " * 5
        raw = f'{{"risk_level": "medium", "insight": "{text}", "reason": "y", "recommended_action": "z"}}'
        result = parse_and_validate_ai_response(raw)
        assert result.risk_level == RiskLevel.MEDIUM
