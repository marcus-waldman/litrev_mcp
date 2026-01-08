"""
Tests for RAG (Retrieval Augmented Generation) tools.

Tests chunking, embedding, database operations, and tool functions.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock


class TestChunking:
    """Tests for text chunking algorithm."""

    def test_chunk_text_basic(self):
        """Test basic text chunking."""
        from litrev_mcp.tools.rag_embed import chunk_text

        text = "First paragraph with some content.\n\nSecond paragraph with more content.\n\nThird paragraph."
        chunks = chunk_text(text, target_tokens=20, overlap_tokens=5)

        assert len(chunks) >= 1
        assert all('text' in c for c in chunks)
        assert all('chunk_index' in c for c in chunks)
        assert all('page_number' in c for c in chunks)

    def test_chunk_text_preserves_content(self):
        """Test that chunking preserves all content."""
        from litrev_mcp.tools.rag_embed import chunk_text

        text = "This is a test. " * 100
        chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)

        # All chunks should have text
        assert all(c['text'].strip() for c in chunks)
        # Chunk indices should be sequential
        indices = [c['chunk_index'] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_text_with_page_breaks(self):
        """Test chunking with page break tracking."""
        from litrev_mcp.tools.rag_embed import chunk_text

        text = "Page 1 content here.\n\nPage 2 content here.\n\nPage 3 content."
        page_breaks = [0, 22, 44]  # Character positions where pages start

        chunks = chunk_text(text, target_tokens=10, overlap_tokens=2, page_breaks=page_breaks)

        assert all('page_number' in c for c in chunks)
        # First chunk should be on page 1
        assert chunks[0]['page_number'] == 1

    def test_chunk_text_empty_input(self):
        """Test chunking with empty input."""
        from litrev_mcp.tools.rag_embed import chunk_text

        chunks = chunk_text("", target_tokens=500)
        assert chunks == []

        chunks = chunk_text("   \n\n  ", target_tokens=500)
        assert chunks == []


class TestTokenEstimation:
    """Tests for token estimation."""

    def test_estimate_tokens(self):
        """Test token estimation."""
        from litrev_mcp.tools.rag_embed import _estimate_tokens

        # Empty string
        assert _estimate_tokens("") == 0

        # Simple sentence
        tokens = _estimate_tokens("Hello world")
        assert tokens > 0
        assert tokens < 10  # Should be roughly 2-3 tokens

        # Longer text
        long_text = "This is a longer piece of text with many words."
        tokens = _estimate_tokens(long_text)
        assert tokens > 5


class TestDatabaseSchema:
    """Tests for DuckDB schema initialization."""

    def test_init_schema(self):
        """Test database schema initialization."""
        import duckdb
        from litrev_mcp.tools.rag_db import _init_schema

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"
            conn = duckdb.connect(str(db_path))
            try:
                _init_schema(conn)

                # Verify tables exist
                tables = conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
                table_names = [t[0] for t in tables]

                assert 'papers' in table_names
                assert 'chunks' in table_names
            finally:
                conn.close()

    def test_paper_crud_operations(self):
        """Test paper CRUD operations."""
        import duckdb
        from litrev_mcp.tools.rag_db import (
            _init_schema,
            insert_paper,
            paper_exists,
            delete_paper,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.duckdb"

            # Mock the connection getter
            conn = duckdb.connect(str(db_path))
            try:
                _init_schema(conn)

                with patch('litrev_mcp.tools.rag_db.get_connection', return_value=conn):
                    # Insert paper
                    insert_paper(
                        item_key="TEST123",
                        citation_key="smith_test_2023",
                        title="Test Paper",
                        authors="Smith, J.",
                        year=2023,
                        project="TEST",
                        pdf_path="/path/to/test.pdf",
                        total_chunks=5,
                    )

                    # Check exists
                    assert paper_exists("TEST123")
                    assert not paper_exists("NONEXISTENT")

                    # Delete paper
                    delete_paper("TEST123")
                    assert not paper_exists("TEST123")
            finally:
                conn.close()


class TestRAGToolsMocked:
    """Tests for RAG tools with mocked dependencies."""

    @pytest.fixture
    def mock_config(self):
        """Mock config manager for tests."""
        with patch('litrev_mcp.tools.rag.config_manager') as mock:
            from litrev_mcp.config import Config, ProjectConfig

            config = Config(
                projects={
                    'TEST': ProjectConfig(
                        name='Test Project',
                        zotero_collection_key='COL123',
                        drive_folder='Literature/TEST',
                    )
                }
            )
            mock.load.return_value = config

            with tempfile.TemporaryDirectory() as tmpdir:
                mock.literature_path = Path(tmpdir) / "Literature"
                mock.literature_path.mkdir(parents=True)
                (mock.literature_path / "TEST").mkdir()
                (mock.literature_path / ".litrev").mkdir()

                yield mock, Path(tmpdir)

    @pytest.mark.asyncio
    async def test_search_papers_project_not_found(self):
        """Test search_papers with non-existent project."""
        from litrev_mcp.tools.rag import search_papers

        with patch('litrev_mcp.tools.rag.config_manager') as mock_config:
            from litrev_mcp.config import Config
            mock_config.load.return_value = Config(projects={})

            result = await search_papers(query="test", project="NONEXISTENT")

            assert result['success'] is False
            assert result['error']['code'] == 'PROJECT_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_index_papers_project_not_found(self):
        """Test index_papers with non-existent project."""
        from litrev_mcp.tools.rag import index_papers

        with patch('litrev_mcp.tools.rag.config_manager') as mock_config:
            from litrev_mcp.config import Config
            mock_config.load.return_value = Config(projects={})

            result = await index_papers(project="NONEXISTENT")

            assert result['success'] is False
            assert result['error']['code'] == 'PROJECT_NOT_FOUND'

    @pytest.mark.asyncio
    async def test_ask_papers_no_results(self):
        """Test ask_papers when no results found."""
        from litrev_mcp.tools.rag import ask_papers

        with patch('litrev_mcp.tools.rag.search_papers') as mock_search:
            mock_search.return_value = {
                'success': True,
                'query': 'test question',
                'count': 0,
                'results': [],
            }

            result = await ask_papers(question="test question")

            assert result['success'] is True
            assert "No relevant passages found" in result['context']
            assert result['sources'] == []

    @pytest.mark.asyncio
    async def test_ask_papers_with_results(self):
        """Test ask_papers formatting with results."""
        from litrev_mcp.tools.rag import ask_papers

        mock_results = [
            {
                'citation_key': 'smith_test_2023',
                'title': 'Test Paper',
                'authors': 'Smith, J.',
                'year': 2023,
                'page_number': 5,
                'text': 'This is relevant content from the paper.',
                'score': 0.85,
            }
        ]

        with patch('litrev_mcp.tools.rag.search_papers') as mock_search:
            mock_search.return_value = {
                'success': True,
                'query': 'test question',
                'count': 1,
                'results': mock_results,
            }

            result = await ask_papers(question="test question")

            assert result['success'] is True
            assert 'smith_test_2023' in result['context']
            assert 'p.5' in result['context']
            assert len(result['sources']) == 1
            assert result['sources'][0]['citation_key'] == 'smith_test_2023'


class TestEmbeddingMocked:
    """Tests for embedding functions with mocked OpenAI."""

    def test_embed_texts_missing_api_key(self):
        """Test that missing API key raises error."""
        from litrev_mcp.tools.rag_embed import embed_texts, EmbeddingError

        with patch.dict('os.environ', {}, clear=True):
            with patch('os.environ.get', return_value=None):
                with pytest.raises(EmbeddingError) as exc:
                    embed_texts(["test text"])
                assert "OPENAI_API_KEY" in str(exc.value)

    def test_embed_texts_empty_list(self):
        """Test embedding empty list returns empty list."""
        from litrev_mcp.tools.rag_embed import embed_texts

        result = embed_texts([])
        assert result == []


class TestPDFExtraction:
    """Tests for PDF text extraction."""

    def test_clean_text(self):
        """Test text cleaning function."""
        from litrev_mcp.tools.rag_embed import _clean_text

        # Test whitespace normalization
        text = "Hello   world\n\n\ntest"
        cleaned = _clean_text(text)
        assert "   " not in cleaned

        # Test empty input
        assert _clean_text("") == ""
        assert _clean_text("   ") == ""


class TestIntegration:
    """Integration tests (skipped if dependencies not available)."""

    @pytest.mark.skipif(
        not Path("C:/Users/marcu/Google Drive/Literature/.litrev").exists(),
        reason="Test environment not configured"
    )
    @pytest.mark.asyncio
    async def test_rag_status(self):
        """Test rag_status function."""
        from litrev_mcp.tools.rag import rag_status

        result = await rag_status()
        assert 'success' in result
