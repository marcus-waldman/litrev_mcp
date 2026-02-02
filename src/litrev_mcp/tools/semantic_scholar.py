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

# Set up R environment - allow env var override
if 'R_HOME' not in os.environ:
    os.environ['R_HOME'] = r'C:\Program Files\R\R-4.5.1'

# Bridge API key: the R package reads Sys.getenv("SEMANTICSCHOLAR_API")
_api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY') or os.environ.get('SEMANTICSCHOLAR_API')
if _api_key and 'SEMANTICSCHOLAR_API' not in os.environ:
    os.environ['SEMANTICSCHOLAR_API'] = _api_key

from rpy2 import robjects
from rpy2.robjects import r, StrVector

# Load the semanticscholar R package
try:
    r('library(semanticscholar)')
    _R_PACKAGE_LOADED = True
except Exception as e:
    _R_PACKAGE_LOADED = False
    _R_LOAD_ERROR = str(e)


def _r_dataframe_to_dicts(df) -> List[Dict]:
    """Convert R dataframe to list of Python dicts."""
    # Check for NULL / None
    if df is robjects.NULL or df is None:
        return []

    # Check via R's is.null (handles rpy2 edge cases)
    try:
        if r('is.null')(df)[0]:
            return []
    except Exception:
        return []

    # Check row count safely
    try:
        nrow_result = r('nrow')(df)
        if nrow_result is robjects.NULL or nrow_result is None:
            return []
        n_rows = int(nrow_result[0])
    except Exception:
        return []

    if n_rows == 0:
        return []

    # Get column names
    col_names = list(r('names')(df))

    results = []
    for i in range(n_rows):
        row = {}
        for col in col_names:
            val = df.rx2(col)[i]
            # Handle R NA values
            try:
                if r('is.na')(val)[0]:
                    row[col] = None
                else:
                    row[col] = val
            except Exception:
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

        # R package returns a named list {total, offset, next, data}
        # Extract the 'data' dataframe
        r_data = r_result.rx2('data')

        # Convert R dataframe to list of dicts
        paper_dicts = _r_dataframe_to_dicts(r_data)

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
            r_result = s2_paper(paper_id, details=StrVector(['references']), limit=max_results)
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

        # R function returns a named list: {offset, citingPaperInfo, next, data}
        # citingPaperInfo = source paper metadata
        # data$citedPaper = dataframe of referenced papers

        # Extract source paper info
        source_paper = {"title": "Unknown", "s2_id": paper_id}
        try:
            paper_info = r_result.rx2('citingPaperInfo')
            if paper_info is not robjects.NULL and paper_info is not None:
                info_names = list(r('names')(paper_info))
                if 'title' in info_names:
                    title_val = paper_info.rx2('title')
                    if title_val is not robjects.NULL:
                        source_paper["title"] = str(title_val[0])
        except Exception:
            pass  # Keep defaults

        # Extract references dataframe
        references = []
        try:
            data_element = r_result.rx2('data')
            if data_element is not robjects.NULL and data_element is not None:
                refs_df = data_element.rx2('citedPaper')
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
        except Exception:
            pass  # Return empty references

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
    if not _R_PACKAGE_LOADED:
        return {
            "success": False,
            "error": {
                "code": "R_PACKAGE_NOT_LOADED",
                "message": f"R semanticscholar package failed to load: {_R_LOAD_ERROR}",
            }
        }

    try:
        # Call R function to get paper with citations
        s2_paper = r['S2_paper2']
        try:
            r_result = s2_paper(paper_id, details=StrVector(['citations']), limit=max_results)
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

        # R function returns a named list: {offset, citedPaperInfo, next, data}
        # citedPaperInfo = source paper metadata
        # data$citingPaper = dataframe of citing papers

        # Extract source paper info
        source_paper = {"title": "Unknown", "s2_id": paper_id}
        try:
            paper_info = r_result.rx2('citedPaperInfo')
            if paper_info is not robjects.NULL and paper_info is not None:
                info_names = list(r('names')(paper_info))
                if 'title' in info_names:
                    title_val = paper_info.rx2('title')
                    if title_val is not robjects.NULL:
                        source_paper["title"] = str(title_val[0])
        except Exception:
            pass  # Keep defaults

        # Extract citations dataframe
        citations = []
        try:
            data_element = r_result.rx2('data')
            if data_element is not robjects.NULL and data_element is not None:
                cites_df = data_element.rx2('citingPaper')
                cite_dicts = _r_dataframe_to_dicts(cites_df)

                for cite_dict in cite_dicts:
                    citations.append({
                        "s2_id": cite_dict.get('paperId'),
                        "title": cite_dict.get('title') or "Untitled",
                        "authors": cite_dict.get('authors') or "Unknown",
                        "year": cite_dict.get('year'),
                        "doi": cite_dict.get('externalIds.DOI'),
                        "citation_count": cite_dict.get('citationCount') or 0,
                        "is_influential": False,  # R package doesn't provide this
                    })
        except Exception:
            pass  # Return empty citations

        result = {
            "success": True,
            "source": "Semantic Scholar",
            "source_paper": source_paper,
            "citation_count": len(citations),
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
