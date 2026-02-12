"""
Tests for extract_concepts with pre-extracted data (extracted_data parameter).
"""

import pytest
import asyncio

from litrev_mcp.tools.argument_map import extract_concepts


@pytest.fixture
def sample_extracted_data():
    """Sample pre-extracted data matching the expected schema."""
    return {
        "suggested_topics": [
            {"name": "Measurement Error", "description": "Effects of measurement error on estimates"}
        ],
        "propositions": [
            {
                "name": "Measurement error causes attenuation bias",
                "definition": "Classical measurement error biases regression coefficients toward zero",
                "source": "insight",
                "suggested_topic": "Measurement Error"
            },
            {
                "name": "Bayesian methods can correct for measurement error",
                "definition": "Bayesian estimation with informative priors can adjust for known error",
                "source": "ai_knowledge",
                "suggested_topic": "Measurement Error"
            }
        ],
        "evidence": [
            {
                "proposition_name": "Measurement error causes attenuation bias",
                "claim": "Effect estimates may be 20-70% smaller than true values (Keogh et al., 2020)",
                "insight_id": "consensus-me-overview"
            }
        ],
        "relationships": [
            {
                "from": "Measurement error causes attenuation bias",
                "to": "Bayesian methods can correct for measurement error",
                "type": "leads_to",
                "source": "ai_knowledge"
            }
        ]
    }


class TestExtractConceptsPreExtracted:
    """Tests for the extracted_data bypass path."""

    def test_returns_success(self, sample_extracted_data):
        result = asyncio.run(extract_concepts(
            project="TEST",
            insight_id="consensus-me-overview",
            extracted_data=sample_extracted_data
        ))
        assert result["success"] is True

    def test_counts_are_correct(self, sample_extracted_data):
        result = asyncio.run(extract_concepts(
            project="TEST",
            insight_id="consensus-me-overview",
            extracted_data=sample_extracted_data
        ))
        assert result["topics_count"] == 1
        assert result["propositions_count"] == 2
        assert result["relationships_count"] == 1
        assert result["evidence_count"] == 1

    def test_extracted_data_passed_through(self, sample_extracted_data):
        result = asyncio.run(extract_concepts(
            project="TEST",
            insight_id="consensus-me-overview",
            extracted_data=sample_extracted_data
        ))
        assert result["extracted"] is sample_extracted_data

    def test_project_and_insight_id_in_result(self, sample_extracted_data):
        result = asyncio.run(extract_concepts(
            project="MY-PROJ",
            insight_id="my-insight",
            extracted_data=sample_extracted_data
        ))
        assert result["project"] == "MY-PROJ"
        assert result["insight_id"] == "my-insight"

    def test_empty_extracted_data(self):
        """Empty dict should still succeed with zero counts."""
        result = asyncio.run(extract_concepts(
            project="TEST",
            insight_id="test-insight",
            extracted_data={}
        ))
        assert result["success"] is True
        assert result["topics_count"] == 0
        assert result["propositions_count"] == 0
        assert result["relationships_count"] == 0
        assert result["evidence_count"] == 0

    def test_no_api_key_needed(self, sample_extracted_data, monkeypatch):
        """extracted_data path should work even without ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = asyncio.run(extract_concepts(
            project="TEST",
            insight_id="test-insight",
            extracted_data=sample_extracted_data
        ))
        assert result["success"] is True
