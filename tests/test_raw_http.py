"""
Tests for raw HTTP helpers (urllib-based API calls).

Tests the raw HTTP functions that bypass httpx to avoid
deadlocks in the MCP server's asyncio event loop.
"""

import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from litrev_mcp.tools.raw_http import (
    async_embed_texts_raw,
    async_embed_query_raw,
    async_anthropic_messages_raw,
    _split_into_token_batches,
    _MAX_TOKENS_PER_BATCH,
)
from litrev_mcp.tools.rag_embed import EmbeddingError


class TestAsyncEmbedTextsRaw:
    """Tests for async_embed_texts_raw."""

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Empty text list should return empty list."""
        result = await async_embed_texts_raw([])
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        """Should raise EmbeddingError without OPENAI_API_KEY."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(EmbeddingError, match="OPENAI_API_KEY"):
                await async_embed_texts_raw(["test text"])

    @pytest.mark.asyncio
    async def test_successful_embedding(self):
        """Should return embeddings from API response."""
        mock_response_body = json.dumps({
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('litrev_mcp.tools.raw_http.get_embedding_dimensions', return_value=256):
                with patch('urllib.request.urlopen', return_value=mock_resp):
                    result = await async_embed_texts_raw(["text1", "text2"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_preserves_order(self):
        """Should sort by index to preserve input order."""
        mock_response_body = json.dumps({
            "data": [
                {"index": 1, "embedding": [0.4, 0.5]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('litrev_mcp.tools.raw_http.get_embedding_dimensions', return_value=256):
                with patch('urllib.request.urlopen', return_value=mock_resp):
                    result = await async_embed_texts_raw(["text1", "text2"])

        assert result[0] == [0.1, 0.2]  # index 0
        assert result[1] == [0.4, 0.5]  # index 1

    @pytest.mark.asyncio
    async def test_api_error_raises_embedding_error(self):
        """API errors should be wrapped in EmbeddingError."""
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('litrev_mcp.tools.raw_http.get_embedding_dimensions', return_value=256):
                with patch('urllib.request.urlopen', side_effect=Exception("Connection failed")):
                    with pytest.raises(EmbeddingError, match="Connection failed"):
                        await async_embed_texts_raw(["test text"])


class TestAsyncEmbedQueryRaw:
    """Tests for async_embed_query_raw."""

    @pytest.mark.asyncio
    async def test_returns_single_embedding(self):
        """Should return a single embedding vector."""
        mock_response_body = json.dumps({
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('litrev_mcp.tools.raw_http.get_embedding_dimensions', return_value=256):
                with patch('urllib.request.urlopen', return_value=mock_resp):
                    result = await async_embed_query_raw("test query")

        assert result == [0.1, 0.2, 0.3]


class TestAsyncAnthropicMessagesRaw:
    """Tests for async_anthropic_messages_raw."""

    @pytest.mark.asyncio
    async def test_missing_api_key(self):
        """Should raise ValueError without ANTHROPIC_API_KEY."""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                await async_anthropic_messages_raw(
                    model="claude-sonnet-4-20250514",
                    max_tokens=256,
                    messages=[{"role": "user", "content": "test"}],
                )

    @pytest.mark.asyncio
    async def test_successful_response(self):
        """Should return text content from API response."""
        mock_response_body = json.dumps({
            "content": [
                {"type": "text", "text": "Hello, world!"}
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('urllib.request.urlopen', return_value=mock_resp):
                result = await async_anthropic_messages_raw(
                    model="claude-sonnet-4-20250514",
                    max_tokens=256,
                    messages=[{"role": "user", "content": "test"}],
                )

        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_explicit_api_key(self):
        """Should use explicitly provided API key."""
        mock_response_body = json.dumps({
            "content": [
                {"type": "text", "text": "response"}
            ]
        }).encode()

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch.dict('os.environ', {}, clear=True):
            with patch('urllib.request.urlopen', return_value=mock_resp) as mock_urlopen:
                result = await async_anthropic_messages_raw(
                    model="claude-sonnet-4-20250514",
                    max_tokens=256,
                    messages=[{"role": "user", "content": "test"}],
                    api_key="explicit-key",
                )

        assert result == "response"
        # Verify the request was made with the explicit key
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert request_obj.get_header("X-api-key") == "explicit-key"

    @pytest.mark.asyncio
    async def test_api_error_propagates(self):
        """API errors should propagate."""
        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch('urllib.request.urlopen', side_effect=Exception("Connection failed")):
                with pytest.raises(Exception, match="Connection failed"):
                    await async_anthropic_messages_raw(
                        model="claude-sonnet-4-20250514",
                        max_tokens=256,
                        messages=[{"role": "user", "content": "test"}],
                    )


class TestSplitIntoTokenBatches:
    """Tests for _split_into_token_batches helper."""

    def test_empty_input(self):
        """Empty list should return empty batches."""
        assert _split_into_token_batches([]) == []

    def test_single_small_text(self):
        """Single small text should be one batch."""
        result = _split_into_token_batches(["hello world"])
        assert len(result) == 1
        assert result[0] == ["hello world"]

    def test_texts_within_limit_single_batch(self):
        """Texts fitting within limit should be one batch."""
        texts = ["word " * 100 for _ in range(10)]  # ~130 tokens each, ~1300 total
        result = _split_into_token_batches(texts)
        assert len(result) == 1
        assert len(result[0]) == 10

    def test_texts_exceeding_limit_split(self):
        """Texts exceeding limit should be split into multiple batches."""
        # Each text: 1000 words * 1.3 = ~1300 tokens
        # 200 texts * 1300 = ~260K tokens > 250K limit
        big_text = "word " * 1000
        texts = [big_text] * 200
        result = _split_into_token_batches(texts)
        assert len(result) >= 2
        # All texts should be accounted for
        total = sum(len(batch) for batch in result)
        assert total == 200

    def test_single_oversized_text(self):
        """A single text exceeding the limit should go in its own batch."""
        # ~325K tokens (250K words * 1.3)
        huge_text = "word " * 250_000
        texts = [huge_text]
        result = _split_into_token_batches(texts)
        assert len(result) == 1
        assert len(result[0]) == 1

    def test_preserves_order(self):
        """Batches should preserve input order."""
        texts = [f"text_{i} " * 100 for i in range(5)]
        result = _split_into_token_batches(texts)
        flattened = [t for batch in result for t in batch]
        assert flattened == texts


class TestAsyncEmbedTextsRawBatching:
    """Tests for token-aware batching in async_embed_texts_raw."""

    @pytest.mark.asyncio
    async def test_large_input_makes_multiple_api_calls(self):
        """Inputs exceeding token limit should result in multiple API calls."""
        # Create texts that will split into 2 batches
        # Each text: 1000 words * 1.3 = ~1300 tokens
        # 200 texts * 1300 = ~260K > 250K limit
        big_text = "word " * 1000
        texts = [big_text] * 200

        call_count = 0

        def mock_urlopen(req, timeout=60):
            nonlocal call_count
            # Parse the request to know how many texts were sent
            payload = json.loads(req.data)
            n = len(payload["input"])
            call_count += 1

            body = json.dumps({
                "data": [
                    {"index": i, "embedding": [float(call_count), float(i)]}
                    for i in range(n)
                ]
            }).encode()

            mock_resp = MagicMock()
            mock_resp.read.return_value = body
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}):
            with patch('litrev_mcp.tools.raw_http.get_embedding_dimensions', return_value=256):
                with patch('urllib.request.urlopen', side_effect=mock_urlopen):
                    result = await async_embed_texts_raw(texts)

        assert call_count >= 2
        assert len(result) == 200
