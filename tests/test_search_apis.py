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
    format_s2_paper_from_r,
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
    """Tests for Semantic Scholar search functionality (R via rpy2)."""

    def test_format_s2_paper_from_r(self):
        """Test formatting S2 paper dict from R package."""
        paper_dict = {
            'paperId': 's2_id_123',
            'title': 'Test Paper',
            'year': 2020,
            'citationCount': 42,
            'abstract': 'Test abstract',
            'externalIds.DOI': '10.1234/test',
            'authors': 'John Smith, Jane Doe',
        }

        result = format_s2_paper_from_r(paper_dict)

        assert result['s2_id'] == 's2_id_123'
        assert result['title'] == 'Test Paper'
        assert result['authors'] == 'John Smith, Jane Doe'
        assert result['year'] == 2020
        assert result['doi'] == '10.1234/test'
        assert result['citation_count'] == 42

    @pytest.mark.asyncio
    async def test_semantic_scholar_search_with_mock(self):
        """Test Semantic Scholar search with mocked R functions."""
        import litrev_mcp.tools.semantic_scholar as s2_mod

        mock_paper_dicts = [
            {
                'paperId': 's2_123',
                'title': 'Test Paper',
                'year': 2020,
                'citationCount': 10,
                'abstract': 'Abstract',
                'externalIds.DOI': '10.1234/test',
                'authors': 'Test Author',
            }
        ]

        # Mock the R result with rx2('data') returning a dataframe
        mock_r_data = MagicMock()
        mock_r_result = MagicMock()
        mock_r_result.rx2 = MagicMock(return_value=mock_r_data)

        # Mock the R function callable
        mock_s2_search = MagicMock(return_value=mock_r_result)

        # Build a dict-like mock for r['S2_search_papers']
        r_dict = {'S2_search_papers': mock_s2_search}
        mock_r = MagicMock()
        mock_r.__getitem__ = lambda self, key: r_dict[key]

        orig_loaded = s2_mod._R_PACKAGE_LOADED
        orig_r = s2_mod.r
        orig_df2d = s2_mod._r_dataframe_to_dicts
        try:
            s2_mod._R_PACKAGE_LOADED = True
            s2_mod.r = mock_r
            s2_mod._r_dataframe_to_dicts = MagicMock(return_value=mock_paper_dicts)

            result = await semantic_scholar_search(query="test query")

            assert result['success'] is True
            assert result['source'] == 'Semantic Scholar'
            assert result['count'] == 1
            assert result['results'][0]['s2_id'] == 's2_123'
            assert result['results'][0]['title'] == 'Test Paper'
        finally:
            s2_mod._R_PACKAGE_LOADED = orig_loaded
            s2_mod.r = orig_r
            s2_mod._r_dataframe_to_dicts = orig_df2d

    @pytest.mark.asyncio
    async def test_semantic_scholar_references_with_mock(self):
        """Test backward snowball with mocked R functions."""
        import litrev_mcp.tools.semantic_scholar as s2_mod
        from rpy2 import robjects as real_robjects

        mock_ref_dicts = [
            {
                'paperId': 'ref_456',
                'title': 'Referenced Paper',
                'year': 2015,
                'citationCount': 100,
                'externalIds.DOI': '10.1234/ref',
                'authors': 'Ref Author',
            }
        ]

        # Build mock R result structure
        # citingPaperInfo with title
        mock_title_vec = MagicMock()
        mock_title_vec.__getitem__ = lambda self, i: 'Source Paper'

        mock_paper_info = MagicMock()
        mock_paper_info.rx2 = lambda name: mock_title_vec if name == 'title' else MagicMock()

        # data element with citedPaper sub-dataframe
        mock_refs_df = MagicMock()
        mock_data = MagicMock()
        mock_data.rx2 = MagicMock(return_value=mock_refs_df)

        def r_result_rx2(name):
            if name == 'citingPaperInfo':
                return mock_paper_info
            elif name == 'data':
                return mock_data
            return MagicMock()

        mock_r_result = MagicMock()
        mock_r_result.rx2 = r_result_rx2

        mock_s2_paper = MagicMock(return_value=mock_r_result)
        r_dict = {'S2_paper2': mock_s2_paper}

        # r('names') needs to return column names for paper_info
        def mock_r_callable(expr):
            if expr == 'names':
                return lambda obj: ['title', 'paperId']
            return MagicMock()

        mock_r = MagicMock()
        mock_r.__getitem__ = lambda self, key: r_dict[key]
        mock_r.__call__ = mock_r_callable
        mock_r.side_effect = mock_r_callable

        orig_loaded = s2_mod._R_PACKAGE_LOADED
        orig_r = s2_mod.r
        orig_robjects = s2_mod.robjects
        orig_df2d = s2_mod._r_dataframe_to_dicts
        try:
            s2_mod._R_PACKAGE_LOADED = True
            s2_mod.r = mock_r
            # Set robjects.NULL to a sentinel that won't match our mocks
            mock_robjects = MagicMock()
            mock_robjects.NULL = object()
            s2_mod.robjects = mock_robjects
            s2_mod._r_dataframe_to_dicts = MagicMock(return_value=mock_ref_dicts)

            result = await semantic_scholar_references(paper_id="10.1234/source")

            assert result['success'] is True
            assert result['source_paper']['title'] == 'Source Paper'
            assert result['reference_count'] == 1
            assert len(result['references']) == 1
            assert result['references'][0]['s2_id'] == 'ref_456'
            assert result['references'][0]['is_influential'] is False
        finally:
            s2_mod._R_PACKAGE_LOADED = orig_loaded
            s2_mod.r = orig_r
            s2_mod.robjects = orig_robjects
            s2_mod._r_dataframe_to_dicts = orig_df2d

    @pytest.mark.asyncio
    async def test_semantic_scholar_citations_with_mock(self):
        """Test forward snowball with mocked R functions."""
        import litrev_mcp.tools.semantic_scholar as s2_mod

        mock_cite_dicts = [
            {
                'paperId': 'cite_789',
                'title': 'Citing Paper',
                'year': 2022,
                'citationCount': 5,
                'externalIds.DOI': '10.1234/cite',
                'authors': 'Cite Author',
            }
        ]

        # Build mock R result structure
        mock_title_vec = MagicMock()
        mock_title_vec.__getitem__ = lambda self, i: 'Source Paper'

        mock_paper_info = MagicMock()
        mock_paper_info.rx2 = lambda name: mock_title_vec if name == 'title' else MagicMock()

        mock_cites_df = MagicMock()
        mock_data = MagicMock()
        mock_data.rx2 = MagicMock(return_value=mock_cites_df)

        def r_result_rx2(name):
            if name == 'citedPaperInfo':
                return mock_paper_info
            elif name == 'data':
                return mock_data
            return MagicMock()

        mock_r_result = MagicMock()
        mock_r_result.rx2 = r_result_rx2

        mock_s2_paper = MagicMock(return_value=mock_r_result)
        r_dict = {'S2_paper2': mock_s2_paper}

        def mock_r_callable(expr):
            if expr == 'names':
                return lambda obj: ['title', 'paperId']
            return MagicMock()

        mock_r = MagicMock()
        mock_r.__getitem__ = lambda self, key: r_dict[key]
        mock_r.__call__ = mock_r_callable
        mock_r.side_effect = mock_r_callable

        orig_loaded = s2_mod._R_PACKAGE_LOADED
        orig_r = s2_mod.r
        orig_robjects = s2_mod.robjects
        orig_df2d = s2_mod._r_dataframe_to_dicts
        try:
            s2_mod._R_PACKAGE_LOADED = True
            s2_mod.r = mock_r
            mock_robjects = MagicMock()
            mock_robjects.NULL = object()
            s2_mod.robjects = mock_robjects
            s2_mod._r_dataframe_to_dicts = MagicMock(return_value=mock_cite_dicts)

            result = await semantic_scholar_citations(paper_id="10.1234/source")

            assert result['success'] is True
            assert result['source_paper']['title'] == 'Source Paper'
            assert result['citation_count'] == 1
            assert len(result['citations']) == 1
            assert result['citations'][0]['s2_id'] == 'cite_789'
            assert result['citations'][0]['is_influential'] is False
        finally:
            s2_mod._R_PACKAGE_LOADED = orig_loaded
            s2_mod.r = orig_r
            s2_mod.robjects = orig_robjects
            s2_mod._r_dataframe_to_dicts = orig_df2d


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
