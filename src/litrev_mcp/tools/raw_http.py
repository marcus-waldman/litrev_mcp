"""
Raw HTTP helpers for OpenAI and Anthropic APIs.

Uses stdlib urllib.request instead of httpx to avoid deadlocks when
synchronous httpx transport runs inside the MCP server's asyncio event loop.
Both sync and async httpx clients conflict with the MCP server's loop;
urllib has no event-loop awareness so it works reliably via asyncio.to_thread().
"""

import asyncio
import json
import os
import urllib.request
from typing import Optional

from litrev_mcp.tools.rag_embed import get_embedding_dimensions, EmbeddingError, _estimate_tokens

# Conservative limit: OpenAI allows ~300K tokens per request for text-embedding-3-small.
# Our word_count * 1.3 heuristic underestimates actual BPE tokens by ~20-25% for
# scientific text, so we use 200K to stay safely under the 300K limit.
_MAX_TOKENS_PER_BATCH = 200_000


def _split_into_token_batches(texts: list[str]) -> list[list[str]]:
    """Split texts into batches that fit within OpenAI's token limit.

    Uses conservative token estimation to stay well under the 300K limit.
    """
    batches = []
    current_batch: list[str] = []
    current_tokens = 0

    for text in texts:
        text_tokens = _estimate_tokens(text)

        # If adding this text would exceed the limit, start a new batch
        # (but if current_batch is empty, add it anyway — let OpenAI handle truly oversized single texts)
        if current_batch and current_tokens + text_tokens > _MAX_TOKENS_PER_BATCH:
            batches.append(current_batch)
            current_batch = [text]
            current_tokens = text_tokens
        else:
            current_batch.append(text)
            current_tokens += text_tokens

    if current_batch:
        batches.append(current_batch)

    return batches


async def async_embed_texts_raw(
    texts: list[str],
    dimensions: Optional[int] = None,
) -> list[list[float]]:
    """
    Generate embeddings for a list of texts via raw HTTP POST to OpenAI.

    Bypasses the OpenAI Python client entirely to avoid httpx deadlocks
    in the MCP server's asyncio event loop.

    Automatically splits large inputs into token-aware batches to stay
    within OpenAI's per-request token limit (~300K for text-embedding-3-small).

    Args:
        texts: List of text strings to embed
        dimensions: Override embedding dimensions (default: use config value)

    Returns:
        List of embedding vectors (one per input text, in order)
    """
    if not texts:
        return []

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY environment variable not set.")

    dims = dimensions if dimensions is not None else get_embedding_dimensions()

    batches = _split_into_token_batches(texts)
    all_embeddings: list[list[float]] = []

    for batch_texts in batches:
        payload = json.dumps({
            "model": "text-embedding-3-small",
            "input": batch_texts,
            "dimensions": dims,
        }).encode()

        req = urllib.request.Request(
            "https://api.openai.com/v1/embeddings",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

        # Scale timeout with batch size (minimum 60s, up to 300s)
        batch_timeout = min(300, max(60, len(batch_texts) // 10 * 10 + 60))

        def _do_request(r=req, t=batch_timeout):
            with urllib.request.urlopen(r, timeout=t) as resp:
                body = json.loads(resp.read())
            # Sort by index to ensure ordering matches input
            sorted_data = sorted(body["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_data]

        try:
            batch_result = await asyncio.to_thread(_do_request)
            all_embeddings.extend(batch_result)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"Failed to generate embeddings: {e}")

    return all_embeddings


async def async_embed_query_raw(query: str) -> list[float]:
    """
    Generate embedding for a single query via raw HTTP POST to OpenAI.

    Convenience wrapper over async_embed_texts_raw.
    """
    result = await async_embed_texts_raw([query])
    return result[0]


async def async_anthropic_messages_raw(
    model: str,
    max_tokens: int,
    messages: list[dict],
    api_key: Optional[str] = None,
) -> str:
    """
    Call Anthropic Messages API via raw HTTP POST.

    Bypasses the Anthropic Python client entirely to avoid httpx deadlocks
    in the MCP server's asyncio event loop.

    Args:
        model: Model ID (e.g., "claude-opus-4-20250514")
        max_tokens: Maximum tokens in response
        messages: List of message dicts with "role" and "content"
        api_key: Optional API key override (default: ANTHROPIC_API_KEY env var)

    Returns:
        The text content of the first content block in the response
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set.")

    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )

    def _do_request():
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
        return body["content"][0]["text"]

    return await asyncio.to_thread(_do_request)
