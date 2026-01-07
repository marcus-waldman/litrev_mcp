"""
Tests for status and dashboard tools.

Tests for project_status and pending_actions.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from litrev_mcp.tools.status import (
    project_status,
    pending_actions,
)
from litrev_mcp.config import Config, ProjectConfig, StatusTags


class TestProjectStatus:
    """Tests for project_status function."""

    @pytest.fixture
    def mock_project_with_zotero(self):
        """Create mock project with Zotero data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.status.config_manager') as mock_config:
                with patch('litrev_mcp.tools.status.get_zotero_client') as mock_zot:
                    # Setup config
                    config = Config(
                        projects={
                            'TEST': ProjectConfig(
                                name='Test Project',
                                zotero_collection_key='COL123',
                                drive_folder='Literature/TEST',
                                notebooklm_notebooks=['TEST - Paper - Topics'],
                            )
                        },
                        status_tags=StatusTags(
                            needs_pdf='_needs-pdf',
                            needs_notebooklm='_needs-notebooklm',
                            complete='_complete',
                        )
                    )
                    mock_config.load.return_value = config

                    # Setup paths
                    lit_path = Path(tmpdir) / "Literature"
                    notes_path = lit_path / "TEST" / "_notes"
                    notes_path.mkdir(parents=True)
                    mock_config.literature_path = lit_path

                    # Create sample insight
                    insight1 = notes_path / "2024-01-15_consensus_test.md"
                    insight1.write_text(
                        "---\n"
                        "date: 2024-01-15\n"
                        "source: consensus\n"
                        "topic: test\n"
                        "---\n\n"
                        "Test content.",
                        encoding='utf-8'
                    )

                    # Setup Zotero mock
                    mock_client = MagicMock()
                    mock_zot.return_value = mock_client

                    # Mock Zotero items
                    today = datetime.now().isoformat()
                    mock_client.collection_items.return_value = [
                        {
                            'data': {
                                'key': 'ITEM1',
                                'title': 'Test Paper 1',
                                'creators': [{'creatorType': 'author', 'lastName': 'Smith'}],
                                'tags': [{'tag': '_needs-pdf'}],
                                'dateAdded': today,
                            }
                        },
                        {
                            'data': {
                                'key': 'ITEM2',
                                'title': 'Test Paper 2',
                                'creators': [{'creatorType': 'author', 'lastName': 'Jones'}],
                                'tags': [{'tag': '_complete'}],
                                'dateAdded': '2023-01-01T00:00:00Z',
                            }
                        },
                    ]

                    yield mock_config, mock_client, lit_path

    @pytest.mark.asyncio
    async def test_project_status_success(self, mock_project_with_zotero):
        mock_config, mock_client, lit_path = mock_project_with_zotero

        # Mock get_notes_path to return the correct path
        with patch('litrev_mcp.tools.status.get_notes_path') as mock_get_notes:
            notes_path = lit_path / "TEST" / "_notes"
            mock_get_notes.return_value = notes_path

            result = await project_status(project="TEST")

            assert result['success'] is True
            assert result['project'] == 'TEST'
            assert result['name'] == 'Test Project'
            assert result['summary']['total'] == 2
            assert result['summary']['needs_pdf'] == 1
            assert result['summary']['complete'] == 1
            assert result['insights']['total'] == 1
            assert result['insights']['by_source']['consensus'] == 1
            assert len(result['recent_additions']) > 0
            assert result['drive_folder'] == 'Literature/TEST'
            assert 'TEST - Paper - Topics' in result['notebooklm_notebooks']

    @pytest.mark.asyncio
    async def test_project_status_invalid_project(self):
        with patch('litrev_mcp.tools.status.config_manager') as mock_config:
            config = Config(projects={})
            mock_config.load.return_value = config

            result = await project_status(project="NONEXISTENT")

            assert result['success'] is False
            assert result['error']['code'] == 'PROJECT_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_project_status_no_zotero(self):
        """Test project status when Zotero collection key is not set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.status.config_manager') as mock_config:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key=None,
                            drive_folder='Literature/TEST',
                        )
                    }
                )
                mock_config.load.return_value = config

                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()
                mock_config.literature_path = lit_path

                result = await project_status(project="TEST")

                assert result['success'] is True
                assert result['summary']['total'] == 0


class TestPendingActions:
    """Tests for pending_actions function."""

    @pytest.fixture
    def mock_projects_with_pending(self):
        """Create mock projects with pending actions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.status.config_manager') as mock_config:
                with patch('litrev_mcp.tools.status.get_zotero_client') as mock_zot:
                    # Setup config
                    config = Config(
                        projects={
                            'TEST': ProjectConfig(
                                name='Test Project',
                                zotero_collection_key='COL123',
                                drive_folder='Literature/TEST',
                                notebooklm_notebooks=['TEST - Notebook'],
                            )
                        },
                        status_tags=StatusTags(
                            needs_pdf='_needs-pdf',
                            needs_notebooklm='_needs-notebooklm',
                            complete='_complete',
                        )
                    )
                    mock_config.load.return_value = config

                    # Setup paths
                    lit_path = Path(tmpdir) / "Literature"
                    lit_path.mkdir()
                    mock_config.literature_path = lit_path

                    # Setup Zotero mock
                    mock_client = MagicMock()
                    mock_zot.return_value = mock_client

                    # Mock items with different statuses
                    mock_client.collection_items.return_value = [
                        {
                            'data': {
                                'key': 'ITEM1',
                                'title': 'Paper Needs PDF',
                                'creators': [{'creatorType': 'author', 'lastName': 'Smith'}],
                                'date': '2020',
                                'DOI': '10.1234/test',
                                'tags': [{'tag': '_needs-pdf'}],
                                'extra': 'Citation Key: smith_test_2020',
                            }
                        },
                        {
                            'data': {
                                'key': 'ITEM2',
                                'title': 'Paper Needs NotebookLM',
                                'creators': [{'creatorType': 'author', 'lastName': 'Jones'}],
                                'date': '2021',
                                'tags': [{'tag': '_needs-notebooklm'}],
                                'extra': 'Citation Key: jones_nlm_2021',
                            }
                        },
                        {
                            'data': {
                                'key': 'ITEM3',
                                'title': 'Paper Complete',
                                'creators': [{'creatorType': 'author', 'lastName': 'Brown'}],
                                'tags': [{'tag': '_complete'}],
                            }
                        },
                    ]

                    yield mock_config, mock_client

    @pytest.mark.asyncio
    async def test_pending_actions_success(self, mock_projects_with_pending):
        mock_config, mock_client = mock_projects_with_pending

        result = await pending_actions()

        assert result['success'] is True
        assert len(result['pdfs_to_acquire']) == 1
        assert len(result['papers_to_add_to_notebooklm']) == 1

        # Check PDF to acquire
        pdf_action = result['pdfs_to_acquire'][0]
        assert pdf_action['project'] == 'TEST'
        assert pdf_action['title'] == 'Paper Needs PDF'
        assert pdf_action['doi'] == '10.1234/test'
        assert pdf_action['doi_url'] == 'https://doi.org/10.1234/test'
        assert pdf_action['drive_filename'] == 'smith_test_2020.pdf'
        assert pdf_action['drive_folder'] == 'Literature/TEST/'

        # Check NotebookLM action
        nlm_action = result['papers_to_add_to_notebooklm'][0]
        assert nlm_action['project'] == 'TEST'
        assert nlm_action['title'] == 'Paper Needs NotebookLM'
        assert nlm_action['citation_key'] == 'jones_nlm_2021'
        assert nlm_action['drive_filename'] == 'jones_nlm_2021.pdf'
        assert nlm_action['drive_full_path'] == 'Literature/TEST/jones_nlm_2021.pdf'
        assert nlm_action['suggested_notebook'] == 'TEST - Notebook'

    @pytest.mark.asyncio
    async def test_pending_actions_empty(self):
        """Test when there are no pending actions."""
        with patch('litrev_mcp.tools.status.config_manager') as mock_config:
            with patch('litrev_mcp.tools.status.get_zotero_client') as mock_zot:
                config = Config(
                    projects={
                        'TEST': ProjectConfig(
                            name='Test Project',
                            zotero_collection_key='COL123',
                            drive_folder='Literature/TEST',
                        )
                    },
                    status_tags=StatusTags()
                )
                mock_config.load.return_value = config

                mock_client = MagicMock()
                mock_zot.return_value = mock_client

                # All papers complete
                mock_client.collection_items.return_value = [
                    {
                        'data': {
                            'key': 'ITEM1',
                            'title': 'Complete Paper',
                            'creators': [],
                            'tags': [{'tag': '_complete'}],
                        }
                    }
                ]

                result = await pending_actions()

                assert result['success'] is True
                assert len(result['pdfs_to_acquire']) == 0
                assert len(result['papers_to_add_to_notebooklm']) == 0

    @pytest.mark.asyncio
    async def test_pending_actions_no_projects(self):
        """Test when there are no projects configured."""
        with patch('litrev_mcp.tools.status.config_manager') as mock_config:
            config = Config(projects={})
            mock_config.load.return_value = config

            result = await pending_actions()

            assert result['success'] is True
            assert len(result['pdfs_to_acquire']) == 0
            assert len(result['papers_to_add_to_notebooklm']) == 0
