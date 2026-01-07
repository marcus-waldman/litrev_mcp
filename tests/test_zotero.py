"""
Tests for Zotero tools.

These tests include:
- Unit tests with mocked Zotero API
- Integration tests (require ZOTERO_API_KEY and ZOTERO_USER_ID to be set)
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock

from litrev_mcp.tools.zotero import (
    get_citation_key_from_extra,
    get_status_from_tags,
    format_authors,
    item_to_dict,
    zotero_list_projects,
    zotero_search,
    zotero_get_citation_key,
    ZoteroAuthError,
)
from litrev_mcp.config import Config, ProjectConfig, StatusTags


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_citation_key_from_extra_found(self):
        extra = "Some note\nCitation Key: smith_example_2020\nAnother line"
        assert get_citation_key_from_extra(extra) == "smith_example_2020"

    def test_get_citation_key_from_extra_case_insensitive(self):
        extra = "citation key: jones_test_2021"
        assert get_citation_key_from_extra(extra) == "jones_test_2021"

    def test_get_citation_key_from_extra_not_found(self):
        extra = "Some other content\nNo citation key here"
        assert get_citation_key_from_extra(extra) is None

    def test_get_citation_key_from_extra_empty(self):
        assert get_citation_key_from_extra("") is None
        assert get_citation_key_from_extra(None) is None

    def test_get_status_from_tags_needs_pdf(self):
        tags = [{'tag': '_needs-pdf'}, {'tag': 'other'}]
        status_tags = {'needs_pdf': '_needs-pdf', 'needs_notebooklm': '_needs-notebooklm', 'complete': '_complete'}
        assert get_status_from_tags(tags, status_tags) == 'needs_pdf'

    def test_get_status_from_tags_complete(self):
        tags = [{'tag': '_complete'}]
        status_tags = {'needs_pdf': '_needs-pdf', 'needs_notebooklm': '_needs-notebooklm', 'complete': '_complete'}
        assert get_status_from_tags(tags, status_tags) == 'complete'

    def test_get_status_from_tags_none(self):
        tags = [{'tag': 'unrelated'}]
        status_tags = {'needs_pdf': '_needs-pdf', 'needs_notebooklm': '_needs-notebooklm', 'complete': '_complete'}
        assert get_status_from_tags(tags, status_tags) is None

    def test_format_authors_single(self):
        creators = [{'creatorType': 'author', 'lastName': 'Smith'}]
        assert format_authors(creators) == "Smith"

    def test_format_authors_multiple(self):
        creators = [
            {'creatorType': 'author', 'lastName': 'Smith'},
            {'creatorType': 'author', 'lastName': 'Jones'},
            {'creatorType': 'author', 'lastName': 'Brown'},
        ]
        assert format_authors(creators) == "Smith, Jones, Brown"

    def test_format_authors_more_than_three(self):
        creators = [
            {'creatorType': 'author', 'lastName': 'Smith'},
            {'creatorType': 'author', 'lastName': 'Jones'},
            {'creatorType': 'author', 'lastName': 'Brown'},
            {'creatorType': 'author', 'lastName': 'Wilson'},
        ]
        assert format_authors(creators) == "Smith et al."

    def test_format_authors_with_name_field(self):
        creators = [{'creatorType': 'author', 'name': 'Organization Name'}]
        assert format_authors(creators) == "Organization Name"

    def test_format_authors_empty(self):
        assert format_authors([]) == "Unknown"

    def test_format_authors_no_authors(self):
        creators = [{'creatorType': 'editor', 'lastName': 'Smith'}]
        assert format_authors(creators) == "Unknown"


class TestItemToDict:
    """Tests for item_to_dict function."""

    def test_item_to_dict_basic(self):
        item = {
            'data': {
                'key': 'ABC123',
                'title': 'Test Paper',
                'creators': [{'creatorType': 'author', 'lastName': 'Smith'}],
                'date': '2020-01-15',
                'DOI': '10.1234/test',
                'itemType': 'journalArticle',
                'extra': 'Citation Key: smith_test_2020',
                'tags': [{'tag': '_needs-pdf'}],
            }
        }

        config = Config(
            status_tags=StatusTags(
                needs_pdf='_needs-pdf',
                needs_notebooklm='_needs-notebooklm',
                complete='_complete',
            )
        )

        result = item_to_dict(item, config)

        assert result['item_key'] == 'ABC123'
        assert result['citation_key'] == 'smith_test_2020'
        assert result['title'] == 'Test Paper'
        assert result['authors'] == 'Smith'
        assert result['year'] == '2020'
        assert result['doi'] == '10.1234/test'
        assert result['status'] == 'needs_pdf'
        assert result['pdf_filename'] == 'smith_test_2020.pdf'


class TestZoteroToolsWithMocks:
    """Tests for Zotero tools using mocked API."""

    @pytest.fixture
    def mock_zotero(self):
        """Create a mock Zotero client."""
        with patch('litrev_mcp.tools.zotero.get_zotero_client') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def mock_config(self):
        """Create a mock config manager."""
        with patch('litrev_mcp.tools.zotero.config_manager') as mock:
            config = Config(
                projects={
                    'TEST': ProjectConfig(
                        name='Test Project',
                        zotero_collection_key='COL123',
                        drive_folder='Literature/TEST',
                    )
                },
                status_tags=StatusTags(
                    needs_pdf='_needs-pdf',
                    needs_notebooklm='_needs-notebooklm',
                    complete='_complete',
                )
            )
            mock.load.return_value = config
            yield mock

    @pytest.mark.asyncio
    async def test_zotero_list_projects_success(self, mock_zotero, mock_config):
        mock_zotero.collections.return_value = [
            {
                'data': {
                    'key': 'COL123',
                    'name': 'Test Project',
                }
            }
        ]
        mock_zotero.collection_items.return_value = [
            {'data': {'tags': [{'tag': '_needs-pdf'}]}},
            {'data': {'tags': [{'tag': '_complete'}]}},
        ]

        result = await zotero_list_projects()

        assert result['success'] is True
        assert len(result['projects']) == 1
        assert result['projects'][0]['name'] == 'Test Project'
        assert result['projects'][0]['total_papers'] == 2
        assert result['projects'][0]['needs_pdf'] == 1
        assert result['projects'][0]['complete'] == 1

    @pytest.mark.asyncio
    async def test_zotero_search_success(self, mock_zotero, mock_config):
        mock_zotero.items.return_value = [
            {
                'data': {
                    'key': 'ITEM1',
                    'title': 'Test Paper About Something',
                    'creators': [{'creatorType': 'author', 'lastName': 'Smith'}],
                    'date': '2020',
                    'DOI': '10.1234/test',
                    'itemType': 'journalArticle',
                    'extra': 'Citation Key: smith_test_2020',
                    'tags': [],
                }
            }
        ]

        result = await zotero_search(query="test paper")

        assert result['success'] is True
        assert result['count'] == 1
        assert result['papers'][0]['title'] == 'Test Paper About Something'
        assert result['papers'][0]['citation_key'] == 'smith_test_2020'

    @pytest.mark.asyncio
    async def test_zotero_get_citation_key_by_title(self, mock_zotero, mock_config):
        mock_zotero.items.return_value = [
            {
                'data': {
                    'key': 'ITEM1',
                    'title': 'Measurement Error Models',
                    'creators': [{'creatorType': 'author', 'lastName': 'Carroll'}],
                    'date': '2006',
                    'extra': 'Citation Key: carroll_measurement_2006',
                }
            }
        ]

        result = await zotero_get_citation_key(title_search="measurement error")

        assert result['success'] is True
        assert len(result['results']) == 1
        assert result['results'][0]['citation_key'] == 'carroll_measurement_2006'
        assert result['results'][0]['pdf_filename'] == 'carroll_measurement_2006.pdf'


class TestZoteroAuthErrors:
    """Tests for authentication error handling."""

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch('litrev_mcp.tools.zotero.get_zotero_api_key', return_value=None):
                with patch('litrev_mcp.tools.zotero.get_zotero_user_id', return_value='123'):
                    result = await zotero_list_projects()
                    assert result['success'] is False
                    assert result['error']['code'] == 'ZOTERO_AUTH_FAILED'

    @pytest.mark.asyncio
    async def test_missing_user_id(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch('litrev_mcp.tools.zotero.get_zotero_api_key', return_value='key123'):
                with patch('litrev_mcp.tools.zotero.get_zotero_user_id', return_value=None):
                    result = await zotero_list_projects()
                    assert result['success'] is False
                    assert result['error']['code'] == 'ZOTERO_AUTH_FAILED'


# Integration tests - only run when credentials are available
@pytest.mark.skipif(
    not (os.environ.get('ZOTERO_API_KEY') and os.environ.get('ZOTERO_USER_ID')),
    reason="Zotero credentials not available"
)
class TestZoteroIntegration:
    """Integration tests that connect to real Zotero API."""

    @pytest.mark.asyncio
    async def test_list_projects_integration(self):
        """Test listing projects with real API."""
        result = await zotero_list_projects()
        assert result['success'] is True
        assert 'projects' in result

    @pytest.mark.asyncio
    async def test_search_integration(self):
        """Test search with real API."""
        result = await zotero_search(query="test")
        assert result['success'] is True
        assert 'papers' in result
