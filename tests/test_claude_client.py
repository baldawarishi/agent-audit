"""Tests for Claude client JSON extraction."""

import pytest

from agent_audit.analyzer.claude_client import AnalyzerClaudeClient


class TestExtractJson:
    def test_extracts_from_json_code_block(self):
        response = '```json\n{"key": "value"}\n```'
        assert AnalyzerClaudeClient.extract_json(response) == '{"key": "value"}'

    def test_extracts_from_bare_code_block(self):
        response = '```\n{"key": "value"}\n```'
        assert AnalyzerClaudeClient.extract_json(response) == '{"key": "value"}'

    def test_returns_raw_input_when_no_code_blocks(self):
        raw = '{"key": "value"}'
        assert AnalyzerClaudeClient.extract_json(raw) == raw

    def test_handles_surrounding_text(self):
        response = 'Here is the result:\n\n```json\n{"data": [1, 2, 3]}\n```\n\nHope this helps!'
        result = AnalyzerClaudeClient.extract_json(response)
        assert '"data"' in result
        assert "Hope this helps" not in result


class TestParseJsonResponse:
    def test_parses_valid_json_response(self):
        response = '```json\n{"status": "ok", "count": 42}\n```'
        result = AnalyzerClaudeClient.parse_json_response(response)
        assert result == {"status": "ok", "count": 42}

    def test_raises_valueerror_on_invalid_json(self):
        with pytest.raises(ValueError, match="Failed to parse JSON"):
            AnalyzerClaudeClient.parse_json_response("not json at all {{{")
