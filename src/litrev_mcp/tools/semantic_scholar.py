"""
Semantic Scholar search and citation analysis for litrev-mcp.

Uses the R semanticscholar package via rpy2 to avoid Windows SSL issues.

Provides:
- Paper search
- Backward snowball (references)
- Forward snowball (citations)
"""

import os
from typing import Any, Optional, List, Dict

# Set up R environment
os.environ['R_HOME'] = r'C:\Program Files\R\R-4.5.1'

from rpy2 import robjects
from rpy2.robjects import r

# Load the semanticscholar R package
try:
    r('library(semanticscholar)')
    _R_PACKAGE_LOADED = True
except Exception as e:
    _R_PACKAGE_LOADED = False
    _R_LOAD_ERROR = str(e)

from litrev_mcp.config import get_semantic_scholar_api_key


def _r_dataframe_to_dicts(df) -> List[Dict]:
    """Convert R dataframe to list of Python dicts."""
    if df is robjects.NULL or r('nrow')(df)[0] == 0:
        return []

    # Get column names
    col_names = list(r('names')(df))
    n_rows = r('nrow')(df)[0]

    results = []
    for i in range(n_rows):
        row = {}
        for col in col_names:
            val = df.rx2(col)[i]
            # Handle R NA values
            if r('is.na')(val)[0]:
                row[col] = None
            else:
                row[col] = val
        results.append(row)

    return results


def format_s2_paper_from_r(paper_dict: dict) -> dict:
    """Format a paper from R package to standard dict."""
    # R package returns different field names, map them
    return {
        "s2_id": paper_dict.get('paperId') or paper_dict.get('paper_id'),
        "title": paper_dict.get('title') or "Untitled",
        "authors": paper_dict.get('authors') or "Unknown",
        "year": paper_dict.get('year'),
        "doi": paper_dict.get('externalIds.DOI'),  # R package may nest this
        "citation_count": paper_dict.get('citationCount') or 0,
        "influential_citation_count": paper_dict.get('influentialCitationCount'),
        "abstract": paper_dict.get('abstract'),
    }


async def semantic_scholar_search(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search Semantic Scholar using R package.

    Args:
        query: Search query
        max_results: Maximum results to return (default 10, max 100)

    Returns:
        Dictionary with search results including S2 IDs and citation counts.
    """
    if not _R_PACKAGE_LOADED:
        return {
            "success": False,
            "error": {
                "code": "R_PACKAGE_NOT_LOADED",
                "message": f"R semanticscholar package failed to load: {_R_LOAD_ERROR}",
            }
        }

    try:
        max_results = min(max_results, 100)

        # Call R function - this may raise an R error if rate limited
        s2_search = r['S2_search_papers']
        try:
            r_result = s2_search(query, limit=max_results)
        except Exception as r_err:
            # R function raised an error (likely rate limit)
            err_msg = str(r_err)
            if '429' in err_msg or 'Too Many Requests' in err_msg:
                return {
                    "success": False,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Semantic Scholar API rate limit exceeded. Please wait a few minutes and try again.",
                    }
                }
            raise  # Re-raise if not rate limit

        # Convert R dataframe to list of dicts
        paper_dicts = _r_dataframe_to_dicts(r_result)

        # Format papers
        papers = []
        for paper_dict in paper_dicts:
            papers.append(format_s2_paper_from_r(paper_dict))

        result = {
            "success": True,
            "source": "Semantic Scholar",
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
    Backward snowball: get papers cited BY a given paper using R package.

    Args:
        paper_id: DOI, S2 paper ID, or PMID (e.g., "10.1234/example", "PMID:12345678")
        max_results: Maximum references to return (default 50)

    Returns:
        Dictionary with source paper info and references list.

    Note:
        The `is_influential` field in results will be False because the
        Semantic Scholar API no longer supports the isInfluential field
        (as of January 2025, GitHub issue #2).
    """
    if not _R_PACKAGE_LOADED:
        return {
            "success": False,
            "error": {
                "code": "R_PACKAGE_NOT_LOADED",
                "message": f"R semanticscholar package failed to load: {_R_LOAD_ERROR}",
            }
        }

    try:
        # Call R function to get paper with references
        s2_paper = r['S2_paper2']
        try:
            r_result = s2_paper(paper_id, details=robjects.StrVector(['references']), limit=max_results)
        except Exception as r_err:
            err_msg = str(r_err)
            if '429' in err_msg or 'Too Many Requests' in err_msg:
                return {
                    "success": False,
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "Semantic Scholar API rate limit exceeded. Please wait a few minutes and try again.",
                    }
                }
            elif 'not found' in err_msg.lower():
                return {
                    "success": False,
                    "error": {
                        "code": "SEMANTIC_SCHOLAR_NOT_FOUND",
                        "message": f"Paper not found: {paper_id}",
                    }
                }
            raise

        # R function returns a list with paper info and references dataframe
        # Extract source paper info (first element of list typically)
        paper_info = r_result.rx2(1)  # Get first list element
        source_paper = {
            "title": str(paper_info.rx2('title')[0]) if 'title' in list(r('names')(paper_info)) else "Unknown",
            "s2_id": paper_id,
        }

        # Extract references dataframe (second element, if exists)
        references = []
        if len(r_result) > 1:
            refs_df = r_result.rx2(2)  # Get references dataframe
            ref_dicts = _r_dataframe_to_dicts(refs_df)

            for ref_dict in ref_dicts:
                references.append({
                    "s2_id": ref_dict.get('paperId'),
                    "title": ref_dict.get('title') or "Untitled",
                    "authors": ref_dict.get('authors') or "Unknown",
                    "year": ref_dict.get('year'),
                    "doi": ref_dict.get('externalIds.DOI'),
                    "citation_count": ref_dict.get('citationCount') or 0,
                    "is_influential": False,  # R package doesn't provide this
                })

        result = {
            "success": True,
            "source": "Semantic Scholar",
            "source_paper": source_paper,
            "reference_count": len(references),
            "references": references,
        }

        # Add workflow guidance
        from litrev_mcp.config import config_manager
        config = config_manager.load()
        if config.workflow.show_guidance:
            result['guidance'] = {
                'next_steps': [
                    f'Review {len(references)} references and add relevant ones with zotero_add_paper',
                    'Backward snowball helps find foundational work',
                    'Document this search strategy with save_search_strategy',
                    'If results close gaps, update _gaps.md'
                ],
                'best_practice': 'Cite highly-cited references as foundational work'
            }

        return result

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
    Forward snowball: get papers that CITE a given paper using R package.

    Args:
        paper_id: DOI, S2 paper ID, or PMID (e.g., "10.1234/example", "PMID:12345678")
        max_results: Maximum citations to return (default 50)

    Returns:
        Dictionary with source paper info and citations list.

    Note:
        The `is_influential` field in results will be False because the
        Semantic Scholar API no longer supports the isInfluential field
        (as of January 2025, GitHub issue #2).
    """
    try:
        s2 = get_s2_client()

        # Get the paper with citations
        paper = s2.get_paper(
            paper_id,
            fields=[
                'title', 'paperId', 'citations', 'citations.paperId',
                'citations.title', 'citations.authors', 'citations.year',
                'citations.externalIds', 'citations.citationCount'
                # Note: citations.isInfluential removed due to API deprecation (GitHub #2)
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

        result = {
            "success": True,
            "source": "Semantic Scholar",
            "source_paper": source_paper,
            "citation_count": len(paper.citations) if paper.citations else 0,
            "citations": citations,
        }

        # Add workflow guidance
        from litrev_mcp.config import config_manager
        config = config_manager.load()
        if config.workflow.show_guidance:
            result['guidance'] = {
                'next_steps': [
                    f'Review {len(citations)} citations and add relevant ones with zotero_add_paper',
                    'Forward snowball helps find recent applications',
                    'Document this search strategy with save_search_strategy',
                    'If results close gaps, update _gaps.md'
                ],
                'best_practice': 'Recent citations show current state of the field'
            }

        return result

    except Exception as e:
        return {
            "success": False,
            "error": {
                "code": "SEMANTIC_SCHOLAR_ERROR",
                "message": str(e),
            }
        }
