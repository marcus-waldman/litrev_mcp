"""
PubMed search for litrev-mcp.

Uses Bio.Entrez from biopython to search PubMed/NCBI databases.
"""

from typing import Any, Optional
from Bio import Entrez

from litrev_mcp.config import get_ncbi_api_key


# Set email for Entrez (required by NCBI)
Entrez.email = "litrev-mcp@example.com"

# Set API key if available (improves rate limits)
api_key = get_ncbi_api_key()
if api_key:
    Entrez.api_key = api_key


async def pubmed_search(
    query: str,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Search PubMed for papers.

    Args:
        query: Search query (supports PubMed syntax)
        max_results: Maximum results to return (default 10, max 50)

    Returns:
        Dictionary with search results including PMIDs, titles, authors, etc.
    """
    try:
        # Limit max_results to 50
        max_results = min(max_results, 50)

        # Search for PMIDs
        search_handle = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=max_results,
            sort="relevance",
        )
        search_results = Entrez.read(search_handle)
        search_handle.close()

        pmids = search_results.get("IdList", [])

        if not pmids:
            return {
                "success": True,
                "source": "PubMed",
                "query": query,
                "count": 0,
                "results": [],
            }

        # Fetch details for each PMID
        fetch_handle = Entrez.efetch(
            db="pubmed",
            id=pmids,
            rettype="medline",
            retmode="xml",
        )
        fetch_results = Entrez.read(fetch_handle)
        fetch_handle.close()

        # Parse results
        papers = []
        for article in fetch_results.get("PubmedArticle", []):
            medline = article.get("MedlineCitation", {})
            article_data = medline.get("Article", {})

            # Extract PMID
            pmid = str(medline.get("PMID", ""))

            # Extract title
            title = article_data.get("ArticleTitle", "")

            # Extract authors
            authors_list = article_data.get("AuthorList", [])
            authors = []
            for author in authors_list:
                last_name = author.get("LastName", "")
                initials = author.get("Initials", "")
                if last_name:
                    if initials:
                        authors.append(f"{last_name} {initials}")
                    else:
                        authors.append(last_name)
            authors_str = ", ".join(authors) if authors else "Unknown"

            # Extract year
            journal_data = article_data.get("Journal", {})
            pub_date = journal_data.get("JournalIssue", {}).get("PubDate", {})
            year = pub_date.get("Year")
            if not year:
                # Try MedlineDate format (e.g., "2020 Jan-Feb")
                medline_date = pub_date.get("MedlineDate", "")
                if medline_date:
                    year = medline_date.split()[0] if medline_date else None

            # Extract journal name
            journal = journal_data.get("Title", "")

            # Extract DOI
            doi = None
            article_ids = article.get("PubmedData", {}).get("ArticleIdList", [])
            for article_id in article_ids:
                if article_id.attributes.get("IdType") == "doi":
                    doi = str(article_id)
                    break

            # Extract abstract
            abstract_data = article_data.get("Abstract", {})
            abstract_texts = abstract_data.get("AbstractText", [])
            if abstract_texts:
                # Handle structured abstracts (list of parts) and simple abstracts (string)
                if isinstance(abstract_texts, list):
                    abstract_parts = []
                    for part in abstract_texts:
                        if hasattr(part, 'attributes') and 'Label' in part.attributes:
                            label = part.attributes['Label']
                            abstract_parts.append(f"{label}: {str(part)}")
                        else:
                            abstract_parts.append(str(part))
                    abstract = " ".join(abstract_parts)
                else:
                    abstract = str(abstract_texts)
            else:
                abstract = None

            papers.append({
                "pmid": pmid,
                "title": title,
                "authors": authors_str,
                "year": year,
                "journal": journal,
                "doi": doi,
                "abstract": abstract,
            })

        result = {
            "success": True,
            "source": "PubMed",
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
                "code": "PUBMED_ERROR",
                "message": str(e),
            }
        }
