"""
Tests for search API tools.

Tests PubMed, Semantic Scholar, and ERIC search functionality.
"""

import os
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from litrev_mcp.tools.pubmed import pubmed_search
from litrev_mcp.tools.semantic_scholar import (
    semantic_scholar_search,
    semantic_scholar_references,
    semantic_scholar_citations,
    format_s2_paper,
)
from litrev_mcp.tools.eric import eric_search


class TestPubMedSearch:
    """Tests for PubMed search functionality."""

    @pytest.mark.asyncio
    async def test_pubmed_search_with_mock(self):
        """Test PubMed search with mocked Bio.Entrez."""
        with patch('litrev_mcp.tools.pubmed.Entrez.esearch') as mock_search:
            with patch('litrev_mcp.tools.pubmed.Entrez.efetch') as mock_fetch:
                with patch('litrev_mcp.tools.pubmed.Entrez.read') as mock_read:
                    # Mock search results
                    mock_search_handle = MagicMock()
                    mock_search.return_value = mock_search_handle
                    mock_read.side_effect = [
                        {'IdList': ['12345678']},  # Search results
                        {  # Fetch results
                            'PubmedArticle': [{
                                'MedlineCitation': {
                                    'PMID': '12345678',
                                    'Article': {
                                        'ArticleTitle': 'Test Article About Something',
                                        'AuthorList': [
                                            {'LastName': 'Smith', 'Initials': 'J'},
                                            {'LastName': 'Doe', 'Initials': 'A'},
                                        ],
                                        'Journal': {
                                            'Title': 'Test Journal',
                                            'JournalIssue': {
                                                'PubDate': {'Year': '2020'}
                                            }
                                        },
                                        'Abstract': {
                                            'AbstractText': ['This is a test abstract.']
                                        },
                                    }
                                },
                                'PubmedData': {
                                    'ArticleIdList': [
                                        MagicMock(attributes={'IdType': 'doi'}, __str__=lambda self: '10.1234/test')
                                    ]
                                }
                            }]
                        }
                    ]

                    mock_fetch_handle = MagicMock()
                    mock_fetch.return_value = mock_fetch_handle

                    result = await pubmed_search(query="test query", max_results=10)

                    assert result['success'] is True
                    assert result['source'] == 'PubMed'
                    assert result['count'] == 1
                    assert len(result['results']) == 1
                    assert result['results'][0]['pmid'] == '12345678'
                    assert result['results'][0]['title'] == 'Test Article About Something'
                    assert result['results'][0]['authors'] == 'Smith J, Doe A'
                    assert result['results'][0]['year'] == '2020'
                    assert result['results'][0]['doi'] == '10.1234/test'

    @pytest.mark.asyncio
    async def test_pubmed_search_no_results(self):
        """Test PubMed search with no results."""
        with patch('litrev_mcp.tools.pubmed.Entrez.esearch') as mock_search:
            with patch('litrev_mcp.tools.pubmed.Entrez.read') as mock_read:
                mock_search_handle = MagicMock()
                mock_search.return_value = mock_search_handle
                mock_read.return_value = {'IdList': []}

                result = await pubmed_search(query="nonexistent query")

                assert result['success'] is True
                assert result['count'] == 0
                assert result['results'] == []

    @pytest.mark.asyncio
    async def test_pubmed_search_max_results_limit(self):
        """Test that max_results is limited to 50."""
        with patch('litrev_mcp.tools.pubmed.Entrez.esearch') as mock_search:
            with patch('litrev_mcp.tools.pubmed.Entrez.read') as mock_read:
                mock_search_handle = MagicMock()
                mock_search.return_value = mock_search_handle
                mock_read.return_value = {'IdList': []}

                await pubmed_search(query="test", max_results=100)

                # Verify esearch was called with retmax=50 (capped)
                mock_search.assert_called_once()
                call_kwargs = mock_search.call_args[1]
                assert call_kwargs['retmax'] == 50


class TestSemanticScholarSearch:
    """Tests for Semantic Scholar search functionality."""

    def test_format_s2_paper(self):
        """Test formatting S2 paper object."""
        mock_paper = MagicMock()
        mock_paper.paperId = 's2_id_123'
        mock_paper.title = 'Test Paper'
        mock_paper.year = 2020
        mock_paper.citationCount = 42
        mock_paper.abstract = 'Test abstract'
        mock_paper.externalIds = {'DOI': '10.1234/test'}

        mock_author1 = MagicMock()
        mock_author1.name = 'John Smith'
        mock_author2 = MagicMock()
        mock_author2.name = 'Jane Doe'
        mock_paper.authors = [mock_author1, mock_author2]

        result = format_s2_paper(mock_paper)

        assert result['s2_id'] == 's2_id_123'
        assert result['title'] == 'Test Paper'
        assert result['authors'] == 'John Smith, Jane Doe'
        assert result['year'] == 2020
        assert result['doi'] == '10.1234/test'
        assert result['citation_count'] == 42

    @pytest.mark.asyncio
    async def test_semantic_scholar_search_with_mock(self):
        """Test Semantic Scholar search with mocked client."""
        with patch('litrev_mcp.tools.semantic_scholar.get_s2_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Create mock paper
            mock_paper = MagicMock()
            mock_paper.paperId = 's2_123'
            mock_paper.title = 'Test Paper'
            mock_paper.year = 2020
            mock_paper.citationCount = 10
            mock_paper.abstract = 'Abstract'
            mock_paper.externalIds = {'DOI': '10.1234/test'}
            mock_author = MagicMock()
            mock_author.name = 'Test Author'
            mock_paper.authors = [mock_author]

            mock_client.search_paper.return_value = [mock_paper]

            result = await semantic_scholar_search(query="test query")

            assert result['success'] is True
            assert result['source'] == 'Semantic Scholar'
            assert result['count'] == 1
            assert result['results'][0]['s2_id'] == 's2_123'
            assert result['results'][0]['title'] == 'Test Paper'

    @pytest.mark.asyncio
    async def test_semantic_scholar_references_with_mock(self):
        """Test backward snowball with mocked client."""
        with patch('litrev_mcp.tools.semantic_scholar.get_s2_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Create mock source paper
            mock_source = MagicMock()
            mock_source.paperId = 'source_123'
            mock_source.title = 'Source Paper'

            # Create mock reference
            mock_ref = MagicMock()
            mock_ref.paperId = 'ref_456'
            mock_ref.title = 'Referenced Paper'
            mock_ref.year = 2015
            mock_ref.citationCount = 100
            mock_ref.externalIds = {'DOI': '10.1234/ref'}
            mock_ref.isInfluential = True
            mock_author = MagicMock()
            mock_author.name = 'Ref Author'
            mock_ref.authors = [mock_author]

            mock_source.references = [mock_ref]
            mock_client.get_paper.return_value = mock_source

            result = await semantic_scholar_references(paper_id="10.1234/source")

            assert result['success'] is True
            assert result['source_paper']['title'] == 'Source Paper'
            assert result['reference_count'] == 1
            assert len(result['references']) == 1
            assert result['references'][0]['s2_id'] == 'ref_456'
            assert result['references'][0]['is_influential'] is True

    @pytest.mark.asyncio
    async def test_semantic_scholar_citations_with_mock(self):
        """Test forward snowball with mocked client."""
        with patch('litrev_mcp.tools.semantic_scholar.get_s2_client') as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # Create mock source paper
            mock_source = MagicMock()
            mock_source.paperId = 'source_123'
            mock_source.title = 'Source Paper'

            # Create mock citation
            mock_cite = MagicMock()
            mock_cite.paperId = 'cite_789'
            mock_cite.title = 'Citing Paper'
            mock_cite.year = 2022
            mock_cite.citationCount = 5
            mock_cite.externalIds = {'DOI': '10.1234/cite'}
            mock_cite.isInfluential = False
            mock_author = MagicMock()
            mock_author.name = 'Cite Author'
            mock_cite.authors = [mock_author]

            mock_source.citations = [mock_cite]
            mock_client.get_paper.return_value = mock_source

            result = await semantic_scholar_citations(paper_id="10.1234/source")

            assert result['success'] is True
            assert result['source_paper']['title'] == 'Source Paper'
            assert result['citation_count'] == 1
            assert len(result['citations']) == 1
            assert result['citations'][0]['s2_id'] == 'cite_789'
            assert result['citations'][0]['is_influential'] is False


class TestERICSearch:
    """Tests for ERIC search functionality."""

    @pytest.mark.asyncio
    async def test_eric_search_with_mock(self):
        """Test ERIC search with mocked HTTP client."""
        mock_response_data = {
            "response": {
                "docs": [
                    {
                        "id": "ED123456",
                        "title": "Test Education Paper",
                        "author": ["Smith, John", "Doe, Jane"],
                        "publicationyear": "2020",
                        "source": "Test Education Journal",
                        "doi": "10.1234/eric",
                        "description": "Test abstract about education.",
                        "publicationtype": ["Journal Article"],
                    }
                ]
            }
        }

        with patch('litrev_mcp.tools.eric.httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await eric_search(query="education test")

            assert result['success'] is True
            assert result['source'] == 'ERIC'
            assert result['count'] == 1
            assert result['results'][0]['eric_id'] == 'ED123456'
            assert result['results'][0]['title'] == 'Test Education Paper'
            assert result['results'][0]['authors'] == 'Smith, John, Doe, Jane'
            assert result['results'][0]['year'] == 2020

    @pytest.mark.asyncio
    async def test_eric_search_no_results(self):
        """Test ERIC search with no results."""
        mock_response_data = {
            "response": {
                "docs": []
            }
        }

        with patch('litrev_mcp.tools.eric.httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await eric_search(query="nonexistent")

            assert result['success'] is True
            assert result['count'] == 0
            assert result['results'] == []

    @pytest.mark.asyncio
    async def test_eric_search_max_results_limit(self):
        """Test that max_results is limited to 50."""
        mock_response_data = {"response": {"docs": []}}

        with patch('litrev_mcp.tools.eric.httpx.AsyncClient') as mock_client_class:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.json.return_value = mock_response_data
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await eric_search(query="test", max_results=100)

            # Verify get was called with rows=50 (capped)
            mock_client.get.assert_called_once()
            call_kwargs = mock_client.get.call_args[1]
            assert call_kwargs['params']['rows'] == 50


# Integration tests - only run when APIs are accessible
@pytest.mark.skipif(
    os.environ.get('SKIP_INTEGRATION_TESTS') == '1',
    reason="Integration tests disabled"
)
class TestSearchAPIsIntegration:
    """Integration tests for search APIs."""

    @pytest.mark.asyncio
    async def test_pubmed_search_integration(self):
        """Test real PubMed search."""
        result = await pubmed_search(query="machine learning", max_results=5)
        assert result['success'] is True
        assert result['count'] <= 5
        if result['count'] > 0:
            assert 'pmid' in result['results'][0]
            assert 'title' in result['results'][0]

    @pytest.mark.asyncio
    async def test_semantic_scholar_search_integration(self):
        """Test real Semantic Scholar search."""
        result = await semantic_scholar_search(query="deep learning", max_results=5)
        assert result['success'] is True
        assert result['count'] <= 5
        if result['count'] > 0:
            assert 's2_id' in result['results'][0]
            assert 'citation_count' in result['results'][0]

    @pytest.mark.asyncio
    async def test_eric_search_integration(self):
        """Test real ERIC search."""
        result = await eric_search(query="educational technology", max_results=5)
        assert result['success'] is True
        assert result['count'] <= 5
        if result['count'] > 0:
            assert 'eric_id' in result['results'][0]
            assert 'title' in result['results'][0]
