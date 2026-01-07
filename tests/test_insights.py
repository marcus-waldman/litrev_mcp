"""
Tests for insights tools.

Tests for saving, searching, analyzing, and listing insights.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from litrev_mcp.tools.insights import (
    save_insight,
    search_insights,
    analyze_insights,
    list_insights,
    sanitize_filename,
    parse_insight_file,
)
from litrev_mcp.config import Config, ProjectConfig


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_sanitize_filename(self):
        assert sanitize_filename("Test Topic") == "test_topic"
        assert sanitize_filename("SIMEX vs Regression Calibration") == "simex_vs_regression_calibration"
        assert sanitize_filename("Test@#$%Topic!") == "testtopic"
        assert sanitize_filename("  spaces  ") == "__spaces__"  # Spaces converted to underscores

    def test_sanitize_filename_length_limit(self):
        long_text = "a" * 100
        result = sanitize_filename(long_text)
        assert len(result) <= 50

    def test_parse_insight_file(self):
        # Create a temporary file with YAML frontmatter
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write("---\n")
            f.write("date: 2024-01-15\n")
            f.write("source: consensus\n")
            f.write("topic: test_topic\n")
            f.write("---\n\n")
            f.write("This is the content.")
            temp_path = Path(f.name)

        try:
            result = parse_insight_file(temp_path)
            assert result is not None
            # YAML may parse date as datetime.date object or string
            date_value = result['frontmatter']['date']
            assert str(date_value) == '2024-01-15'
            assert result['frontmatter']['source'] == 'consensus'
            assert result['content'] == 'This is the content.'
        finally:
            temp_path.unlink()


class TestSaveInsight:
    """Tests for save_insight function."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config with temp directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
                # Set up project config
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_manager.load.return_value = config

                # Set up paths
                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()
                mock_manager.literature_path = lit_path

                yield mock_manager, lit_path

    @pytest.mark.asyncio
    async def test_save_insight_success(self, mock_config):
        mock_manager, lit_path = mock_config

        result = await save_insight(
            project="TEST",
            source="consensus",
            topic="Test Topic",
            content="This is test content.",
            query="test query",
            papers_referenced=["smith_2020", "jones_2021"],
        )

        assert result['success'] is True
        assert 'filepath' in result

        # Verify file was created
        filepath = Path(result['filepath'])
        assert filepath.exists()

        # Verify content
        content = filepath.read_text(encoding='utf-8')
        assert "date:" in content
        assert "source: consensus" in content
        assert "topic: Test Topic" in content
        assert "query: test query" in content
        assert "papers_referenced:" in content
        assert "This is test content." in content

    @pytest.mark.asyncio
    async def test_save_insight_invalid_project(self, mock_config):
        mock_manager, lit_path = mock_config

        result = await save_insight(
            project="NONEXISTENT",
            source="consensus",
            topic="Test",
            content="Content",
        )

        assert result['success'] is False
        assert result['error']['code'] == 'PROJECT_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_save_insight_invalid_source(self, mock_config):
        mock_manager, lit_path = mock_config

        result = await save_insight(
            project="TEST",
            source="invalid_source",
            topic="Test",
            content="Content",
        )

        assert result['success'] is False
        assert result['error']['code'] == 'INVALID_SOURCE'


class TestSearchInsights:
    """Tests for search_insights function."""

    @pytest.fixture
    def mock_insights_dir(self):
        """Create temporary insights directory with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_manager.load.return_value = config

                # Create insights directory
                lit_path = Path(tmpdir) / "Literature"
                notes_path = lit_path / "TEST" / "_notes"
                notes_path.mkdir(parents=True)
                mock_manager.literature_path = lit_path

                # Create sample insight files
                insight1 = notes_path / "2024-01-15_consensus_glucose_methods.md"
                insight1.write_text(
                    "---\n"
                    "date: 2024-01-15\n"
                    "source: consensus\n"
                    "topic: glucose_methods\n"
                    "query: glucose measurement error\n"
                    "---\n\n"
                    "SIMEX is commonly used when the error distribution is known.",
                    encoding='utf-8'
                )

                insight2 = notes_path / "2024-01-16_notebooklm_simex_comparison.md"
                insight2.write_text(
                    "---\n"
                    "date: 2024-01-16\n"
                    "source: notebooklm\n"
                    "topic: simex_comparison\n"
                    "---\n\n"
                    "Regression calibration offers a simpler alternative to SIMEX.",
                    encoding='utf-8'
                )

                yield mock_manager, notes_path

    @pytest.mark.asyncio
    async def test_search_insights_found(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await search_insights(query="SIMEX", project="TEST")

        assert result['success'] is True
        assert result['total_matches'] >= 1
        assert any('simex' in match['content'].lower() for match in result['matches'])

    @pytest.mark.asyncio
    async def test_search_insights_no_matches(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await search_insights(query="nonexistent_term", project="TEST")

        assert result['success'] is True
        assert result['total_matches'] == 0

    @pytest.mark.asyncio
    async def test_search_insights_source_filter(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await search_insights(query="SIMEX", project="TEST", source="consensus")

        assert result['success'] is True
        if result['total_matches'] > 0:
            assert all(match['source'] == 'consensus' for match in result['matches'])


class TestAnalyzeInsights:
    """Tests for analyze_insights function."""

    @pytest.fixture
    def mock_insights_dir(self):
        """Create temporary insights directory with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_manager.load.return_value = config

                # Create insights directory
                lit_path = Path(tmpdir) / "Literature"
                notes_path = lit_path / "TEST" / "_notes"
                notes_path.mkdir(parents=True)
                mock_manager.literature_path = lit_path

                # Create sample insight
                insight1 = notes_path / "2024-01-15_consensus_test.md"
                insight1.write_text(
                    "---\n"
                    "date: 2024-01-15\n"
                    "source: consensus\n"
                    "topic: test\n"
                    "---\n\n"
                    "Test content for analysis.",
                    encoding='utf-8'
                )

                yield mock_manager, notes_path

    @pytest.mark.asyncio
    async def test_analyze_insights_answer_mode(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await analyze_insights(
            question="What about test?",
            project="TEST",
            mode="answer",
        )

        assert result['success'] is True
        assert result['mode'] == 'answer'
        assert 'synthesis' in result

    @pytest.mark.asyncio
    async def test_analyze_insights_compare_mode(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await analyze_insights(
            question="Compare sources",
            project="TEST",
            mode="compare",
        )

        assert result['success'] is True
        assert result['mode'] == 'compare'

    @pytest.mark.asyncio
    async def test_analyze_insights_no_matches(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await analyze_insights(
            question="nonexistent topic",
            project="TEST",
        )

        assert result['success'] is True
        assert result['insights_analyzed'] == 0


class TestListInsights:
    """Tests for list_insights function."""

    @pytest.fixture
    def mock_insights_dir(self):
        """Create temporary insights directory with sample files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_manager.load.return_value = config

                # Create insights directory
                lit_path = Path(tmpdir) / "Literature"
                notes_path = lit_path / "TEST" / "_notes"
                notes_path.mkdir(parents=True)
                mock_manager.literature_path = lit_path

                # Create multiple insights
                insight1 = notes_path / "2024-01-15_consensus_topic1.md"
                insight1.write_text("---\ndate: 2024-01-15\nsource: consensus\n---\nContent 1", encoding='utf-8')

                insight2 = notes_path / "2024-01-16_notebooklm_topic2.md"
                insight2.write_text("---\ndate: 2024-01-16\nsource: notebooklm\n---\nContent 2", encoding='utf-8')

                insight3 = notes_path / "2024-01-17_synthesis_topic3.md"
                insight3.write_text("---\ndate: 2024-01-17\nsource: synthesis\n---\nContent 3", encoding='utf-8')

                yield mock_manager, notes_path

    @pytest.mark.asyncio
    async def test_list_insights_all(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await list_insights(project="TEST")

        assert result['success'] is True
        assert result['total_insights'] == 3
        assert len(result['insights']) == 3
        assert result['by_source']['consensus'] == 1
        assert result['by_source']['notebooklm'] == 1
        assert result['by_source']['synthesis'] == 1

    @pytest.mark.asyncio
    async def test_list_insights_filtered_by_source(self, mock_insights_dir):
        mock_manager, notes_path = mock_insights_dir

        result = await list_insights(project="TEST", source="consensus")

        assert result['success'] is True
        assert result['total_insights'] == 1
        assert all(ins['source'] == 'consensus' for ins in result['insights'])

    @pytest.mark.asyncio
    async def test_list_insights_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_manager.load.return_value = config

                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()
                mock_manager.literature_path = lit_path

                result = await list_insights(project="TEST")

                assert result['success'] is True
                assert result['total_insights'] == 0
                assert result['insights'] == []

    @pytest.mark.asyncio
    async def test_list_insights_invalid_project(self):
        with patch('litrev_mcp.tools.insights.config_manager') as mock_manager:
            config = Config(projects={})
            mock_manager.load.return_value = config

            result = await list_insights(project="NONEXISTENT")

            assert result['success'] is False
            assert result['error']['code'] == 'PROJECT_NOT_FOUND'
