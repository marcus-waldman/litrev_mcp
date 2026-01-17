"""
ERIC (Education Resources Information Center) search for litrev-mcp.

ERIC is the largest education database, providing access to education
literature and resources.
"""

from typing import Any, Optional
import httpx


ERIC_API_BASE = "https://api.ies.ed.gov/eric/"


async def eric_search(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search ERIC for education research papers.

    Args:
        query: Search query
        max_results: Maximum results to return (default 10, max 50)

    Returns:
        Dictionary with search results including ERIC IDs.
    """
    try:
        max_results = min(max_results, 50)

        # Build query parameters
        params = {
            "search": query,
            "rows": max_results,
            "format": "json",
        }

        # Make request to ERIC API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(ERIC_API_BASE, params=params)
            response.raise_for_status()
            data = response.json()

        # Parse results
        papers = []
        docs = data.get("response", {}).get("docs", [])

        for doc in docs:
            # Extract ERIC ID
            eric_id = doc.get("id", "")

            # Extract title
            title = doc.get("title", "Untitled")

            # Extract authors
            authors_list = doc.get("author", [])
            if isinstance(authors_list, list):
                authors_str = ", ".join(authors_list)
            else:
                authors_str = authors_list if authors_list else "Unknown"

            # Extract year
            year = doc.get("publicationyear")
            if year:
                try:
                    year = int(year)
                except (ValueError, TypeError):
                    year = None

            # Extract source (journal/publication)
            source = doc.get("source", "")

            # Extract DOI if available
            doi = doc.get("doi")

            # Extract abstract/description
            abstract = doc.get("description")

            # Extract document type
            doc_type = doc.get("publicationtype", [])
            if isinstance(doc_type, list) and doc_type:
                doc_type = doc_type[0]

            papers.append({
                "eric_id": eric_id,
                "title": title,
                "authors": authors_str,
                "year": year,
                "source": source,
                "doi": doi,
                "abstract": abstract,
                "publication_type": doc_type,
            })

        result = {
            "success": True,
            "source": "ERIC",
            "query": query,
            "count": len(papers),
            "results": papers,
        }

        # Add workflow guidance
        from litrev_mcp.config import config_manager
        config = config_manager.load()
        if config.workflow.show_guidance:
            result['guidance'] = {
                'next_steps': [
                    f'Review {len(papers)} papers and add relevant ones with zotero_add_paper',
                    'Document this search strategy with save_search_strategy',
                    'If results close gaps, update _gaps.md',
                    'If no relevant results found, document as failed search (still valuable!)'
                ],
                'best_practice': 'Record search query, database, and results for reproducibility'
            }

        return result

    except httpx.HTTPStatusError as e:
        return {
            "success": False,
            "error": {
                "code": "ERIC_HTTP_ERROR",
                "message": f"HTTP {e.response.status_code}: {str(e)}",
            }
        }
    except httpx.RequestError as e:
        return {
            "success": False,
            "error": {
                "code": "ERIC_REQUEST_ERROR",
                "message": f"Request failed: {str(e)}",
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "ERIC_ERROR",
                "message": str(e),
            }
        }
