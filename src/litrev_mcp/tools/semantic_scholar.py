"""
Semantic Scholar search and citation analysis for litrev-mcp.

Provides:
- Paper search
- Backward snowball (references)
- Forward snowball (citations)
"""

from typing import Any, Optional
from semanticscholar import SemanticScholar

from litrev_mcp.config import get_semantic_scholar_api_key


def get_s2_client() -> SemanticScholar:
    """Get Semantic Scholar client with optional API key."""
    api_key = get_semantic_scholar_api_key()
    if api_key:
        return SemanticScholar(api_key=api_key)
    return SemanticScholar()


def format_s2_paper(paper) -> dict:
    """Format a Semantic Scholar paper object to standard dict."""
    # Extract authors
    authors = []
    if paper.authors:
        for author in paper.authors:
            if hasattr(author, 'name'):
                authors.append(author.name)
    authors_str = ", ".join(authors) if authors else "Unknown"

    # Extract DOI
    doi = None
    if hasattr(paper, 'externalIds') and paper.externalIds:
        doi = paper.externalIds.get('DOI')

    return {
        "s2_id": paper.paperId,
        "title": paper.title or "Untitled",
        "authors": authors_str,
        "year": paper.year,
        "doi": doi,
        "citation_count": paper.citationCount or 0,
        "influential_citation_count": getattr(paper, 'influentialCitationCount', None),
        "abstract": paper.abstract,
    }


async def semantic_scholar_search(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search Semantic Scholar.

    Args:
        query: Search query
        max_results: Maximum results to return (default 10, max 100)

    Returns:
        Dictionary with search results including S2 IDs and citation counts.
    """
    try:
        max_results = min(max_results, 100)

        s2 = get_s2_client()
        results = s2.search_paper(query, limit=max_results)

        papers = []
        for paper in results:
            papers.append(format_s2_paper(paper))

        return {
            "success": True,
            "source": "Semantic Scholar",
            "query": query,
            "count": len(papers),
            "results": papers,
        }

    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "SEMANTIC_SCHOLAR_ERROR",
                "message": str(e),
            }
        }


async def semantic_scholar_references(
    paper_id: str,
    max_results: int = 50,
) -> dict[str, Any]:
    """
    Backward snowball: get papers cited BY a given paper.

    Args:
        paper_id: DOI, S2 paper ID, or PMID (e.g., "10.1234/example", "PMID:12345678")
        max_results: Maximum references to return (default 50)

    Returns:
        Dictionary with source paper info and references list.
    """
    try:
        s2 = get_s2_client()

        # Get the paper with references
        paper = s2.get_paper(
            paper_id,
            fields=[
                'title', 'paperId', 'references', 'references.paperId',
                'references.title', 'references.authors', 'references.year',
                'references.externalIds', 'references.citationCount',
                'references.isInfluential'
            ]
        )

        if not paper:
            return {
                "success": False,
                "error": {
                    "code": "SEMANTIC_SCHOLAR_NOT_FOUND",
                    "message": f"Paper not found: {paper_id}",
                }
            }

        # Format source paper
        source_paper = {
            "title": paper.title,
            "s2_id": paper.paperId,
        }

        # Get references
        references = []
        if paper.references:
            for ref in paper.references[:max_results]:
                if ref:
                    # Extract DOI
                    doi = None
                    if hasattr(ref, 'externalIds') and ref.externalIds:
                        doi = ref.externalIds.get('DOI')

                    # Extract authors
                    authors = []
                    if hasattr(ref, 'authors') and ref.authors:
                        for author in ref.authors:
                            if hasattr(author, 'name'):
                                authors.append(author.name)
                    authors_str = ", ".join(authors) if authors else "Unknown"

                    # Check if influential
                    is_influential = False
                    if hasattr(ref, 'isInfluential'):
                        is_influential = ref.isInfluential

                    references.append({
                        "s2_id": ref.paperId,
                        "title": ref.title or "Untitled",
                        "authors": authors_str,
                        "year": ref.year,
                        "doi": doi,
                        "citation_count": ref.citationCount or 0,
                        "is_influential": is_influential,
                    })

        return {
            "success": True,
            "source": "Semantic Scholar",
            "source_paper": source_paper,
            "reference_count": len(paper.references) if paper.references else 0,
            "references": references,
        }

    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "SEMANTIC_SCHOLAR_ERROR",
                "message": str(e),
            }
        }


async def semantic_scholar_citations(
    paper_id: str,
    max_results: int = 50,
) -> dict[str, Any]:
    """
    Forward snowball: get papers that CITE a given paper.

    Args:
        paper_id: DOI, S2 paper ID, or PMID (e.g., "10.1234/example", "PMID:12345678")
        max_results: Maximum citations to return (default 50)

    Returns:
        Dictionary with source paper info and citations list.
    """
    try:
        s2 = get_s2_client()

        # Get the paper with citations
        paper = s2.get_paper(
            paper_id,
            fields=[
                'title', 'paperId', 'citations', 'citations.paperId',
                'citations.title', 'citations.authors', 'citations.year',
                'citations.externalIds', 'citations.citationCount',
                'citations.isInfluential'
            ]
        )

        if not paper:
            return {
                "success": False,
                "error": {
                    "code": "SEMANTIC_SCHOLAR_NOT_FOUND",
                    "message": f"Paper not found: {paper_id}",
                }
            }

        # Format source paper
        source_paper = {
            "title": paper.title,
            "s2_id": paper.paperId,
        }

        # Get citations
        citations = []
        if paper.citations:
            for cite in paper.citations[:max_results]:
                if cite:
                    # Extract DOI
                    doi = None
                    if hasattr(cite, 'externalIds') and cite.externalIds:
                        doi = cite.externalIds.get('DOI')

                    # Extract authors
                    authors = []
                    if hasattr(cite, 'authors') and cite.authors:
                        for author in cite.authors:
                            if hasattr(author, 'name'):
                                authors.append(author.name)
                    authors_str = ", ".join(authors) if authors else "Unknown"

                    # Check if influential
                    is_influential = False
                    if hasattr(cite, 'isInfluential'):
                        is_influential = cite.isInfluential

                    citations.append({
                        "s2_id": cite.paperId,
                        "title": cite.title or "Untitled",
                        "authors": authors_str,
                        "year": cite.year,
                        "doi": doi,
                        "citation_count": cite.citationCount or 0,
                        "is_influential": is_influential,
                    })

        return {
            "success": True,
            "source": "Semantic Scholar",
            "source_paper": source_paper,
            "citation_count": len(paper.citations) if paper.citations else 0,
            "citations": citations,
        }

    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "SEMANTIC_SCHOLAR_ERROR",
                "message": str(e),
            }
        }
