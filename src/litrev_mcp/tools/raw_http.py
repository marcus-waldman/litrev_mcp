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

from litrev_mcp.tools.rag_embed import get_embedding_dimensions, EmbeddingError


async def async_embed_texts_raw(
    texts: list[str],
    dimensions: Optional[int] = None,
) -> list[list[float]]:
    """
    Generate embeddings for a list of texts via raw HTTP POST to OpenAI.

    Bypasses the OpenAI Python client entirely to avoid httpx deadlocks
    in the MCP server's asyncio event loop.

    Args:
        texts: List of text strings to embed
        dimensions: Override embedding dimensions (default: use config value)

    Returns:
        List of embedding vectors
    """
    if not texts:
        return []

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY environment variable not set.")

    dims = dimensions if dimensions is not None else get_embedding_dimensions()

    payload = json.dumps({
        "model": "text-embedding-3-small",
        "input": texts,
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

    def _do_request():
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
        # Sort by index to ensure ordering matches input
        sorted_data = sorted(body["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in sorted_data]

    try:
        return await asyncio.to_thread(_do_request)
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"Failed to generate embeddings: {e}")


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
