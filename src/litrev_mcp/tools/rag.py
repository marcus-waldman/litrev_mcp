"""
RAG (Retrieval Augmented Generation) tools for literature search.

Provides semantic search over indexed PDF content using OpenAI embeddings
and DuckDB vector similarity search.
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

from litrev_mcp.config import config_manager
from litrev_mcp.tools.zotero import get_zotero_client, get_citation_key_from_extra, format_authors
from litrev_mcp.tools.pdf_utils import generate_citation_key
from litrev_mcp.tools.rag_db import (
    get_connection,
    paper_exists,
    delete_paper,
    insert_paper,
    insert_chunk,
    insert_chunks_batch,
    search_similar,
    get_indexed_papers,
    get_stats,
)
from litrev_mcp.tools.rag_embed import (
    extract_pdf_text_with_pages,
    chunk_text,
    embed_texts,
    embed_query,
    EmbeddingError,
)
from litrev_mcp.progress import ProgressTracker, TaskStage, progress_server
from litrev_mcp.tools.context import get_context_text


async def index_papers(
    project: str,
    force_reindex: bool = False,
    show_progress: bool = True,
    max_concurrent: int = 5,
) -> dict[str, Any]:
    """
    Index PDFs from a project for semantic search.

    Extracts text from PDFs in the project folder, chunks it,
    generates embeddings via OpenAI, and stores in DuckDB.

    Args:
        project: Project code (e.g., 'MI-IC')
        force_reindex: If True, reindex papers even if already indexed
        show_progress: If True, open browser-based progress dashboard
        max_concurrent: Maximum papers to process concurrently (1-20, default 5)

    Returns:
        {
            success: bool,
            project: str,
            indexed: [{item_key, citation_key, title, chunks}],
            skipped: [{item_key, citation_key, reason}],
            errors: [{item_key, error}],
            summary: str
        }
    """
    try:
        config = config_manager.load()

        # Validate project
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found in config"
                }
            }

        proj_config = config.projects[project]
        collection_key = proj_config.zotero_collection_key

        if not collection_key:
            return {
                'success': False,
                'error': {
                    'code': 'COLLECTION_NOT_CONFIGURED',
                    'message': f"No Zotero collection configured for project '{project}'"
                }
            }

        # Get project folder path
        lit_path = config_manager.literature_path
        project_path = lit_path / project

        if not project_path.exists():
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_FOLDER_NOT_FOUND',
                    'message': f"Project folder not found: {project_path}"
                }
            }

        # Validate max_concurrent
        max_concurrent = min(max(1, max_concurrent), 20)

        # Get Zotero items for metadata
        zot = get_zotero_client()
        items = zot.collection_items(collection_key, itemType='-attachment')

        # Initialize database connection
        get_connection()

        # Create progress tracker
        tracker = ProgressTracker(
            operation_type="index_papers",
            project=project,
        )
        tracker.set_total(len(items))

        # Process with or without progress UI
        if show_progress:
            async with progress_server(tracker, auto_open_browser=True):
                results = await _process_papers_parallel(
                    items=items,
                    project_path=project_path,
                    project=project,
                    force_reindex=force_reindex,
                    tracker=tracker,
                    max_concurrent=max_concurrent,
                )
                summary = f"Indexed {len(results['indexed'])} papers ({sum(p['chunks'] for p in results['indexed'])} chunks), skipped {len(results['skipped'])}, errors {len(results['errors'])}"
                await tracker.finish(summary)
                # Brief delay to let browser show completion
                await asyncio.sleep(1)
        else:
            results = await _process_papers_parallel(
                items=items,
                project_path=project_path,
                project=project,
                force_reindex=force_reindex,
                tracker=tracker,
                max_concurrent=max_concurrent,
            )
            summary = f"Indexed {len(results['indexed'])} papers ({sum(p['chunks'] for p in results['indexed'])} chunks), skipped {len(results['skipped'])}, errors {len(results['errors'])}"

        return {
            'success': True,
            'project': project,
            **results,
            'summary': summary,
        }

    except EmbeddingError as e:
        return {
            'success': False,
            'error': {
                'code': 'EMBEDDING_ERROR',
                'message': str(e)
            }
        }
    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'INDEX_ERROR',
                'message': str(e)
            }
        }


async def _process_papers_parallel(
    items: list,
    project_path: Path,
    project: str,
    force_reindex: bool,
    tracker: ProgressTracker,
    max_concurrent: int = 5,
) -> dict:
    """
    Process papers in parallel with semaphore-controlled concurrency.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_one(item):
        async with semaphore:
            item_data = item.get('data', {})
            item_key = item_data.get('key')
            citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
            title = item_data.get('title', 'Untitled')

            # Register task with tracker
            await tracker.start_task(item_key, citation_key, title)

            try:
                result = await _index_single_paper_tracked(
                    item_data=item_data,
                    project_path=project_path,
                    project=project,
                    force_reindex=force_reindex,
                    tracker=tracker,
                )

                if result['status'] == 'indexed':
                    await tracker.complete_task(item_key, TaskStage.COMPLETE)
                    return ('indexed', {
                        'item_key': item_key,
                        'citation_key': citation_key,
                        'title': title,
                        'chunks': result['chunks'],
                    })
                else:
                    await tracker.complete_task(item_key, TaskStage.SKIPPED)
                    return ('skipped', {
                        'item_key': item_key,
                        'citation_key': citation_key,
                        'reason': result['reason'],
                    })

            except Exception as e:
                await tracker.complete_task(
                    item_key,
                    TaskStage.ERROR,
                    error_message=str(e)
                )
                return ('error', {
                    'item_key': item_key,
                    'citation_key': citation_key,
                    'error': str(e),
                })

    # Process all items concurrently
    tasks = [process_one(item) for item in items]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Categorize results
    indexed = []
    skipped = []
    errors = []

    for result in results:
        if isinstance(result, Exception):
            errors.append({'error': str(result)})
        elif result[0] == 'indexed':
            indexed.append(result[1])
        elif result[0] == 'skipped':
            skipped.append(result[1])
        elif result[0] == 'error':
            errors.append(result[1])

    return {'indexed': indexed, 'skipped': skipped, 'errors': errors}


async def _index_single_paper_tracked(
    item_data: dict,
    project_path: Path,
    project: str,
    force_reindex: bool,
    tracker: ProgressTracker,
) -> dict:
    """Index a single paper with progress tracking and async wrappers for blocking calls."""
    item_key = item_data.get('key')
    citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
    title = item_data.get('title', 'Untitled')

    # Check if already indexed
    if not force_reindex and await asyncio.to_thread(paper_exists, item_key):
        return {'status': 'skipped', 'reason': 'Already indexed'}

    # Find PDF file
    pdf_path = None
    if citation_key:
        candidate = project_path / f"{citation_key}.pdf"
        if candidate.exists():
            pdf_path = candidate

    # If no citation key in Extra, try to generate one from metadata
    if not pdf_path:
        authors = format_authors(item_data.get('creators', []))
        year = item_data.get('date', '')[:4] if item_data.get('date') else ''
        if title and authors and year:
            generated_key = generate_citation_key(title, authors, year)
            candidate = project_path / f"{generated_key}.pdf"
            if candidate.exists():
                citation_key = generated_key
                pdf_path = candidate

    if not pdf_path:
        return {'status': 'skipped', 'reason': 'No PDF found'}

    # Stage: Extracting
    await tracker.update_task(item_key, stage=TaskStage.EXTRACTING)

    try:
        # Wrap blocking pdfplumber call
        full_text, page_breaks = await asyncio.to_thread(
            extract_pdf_text_with_pages, pdf_path
        )
    except Exception as e:
        return {'status': 'skipped', 'reason': f'PDF extraction failed: {e}'}

    if not full_text.strip():
        return {'status': 'skipped', 'reason': 'PDF has no extractable text'}

    # Stage: Chunking
    await tracker.update_task(item_key, stage=TaskStage.CHUNKING)

    chunks = await asyncio.to_thread(
        chunk_text, full_text, page_breaks=page_breaks
    )

    if not chunks:
        return {'status': 'skipped', 'reason': 'No chunks generated'}

    await tracker.update_task(item_key, chunks_total=len(chunks))

    # Stage: Embedding
    await tracker.update_task(item_key, stage=TaskStage.EMBEDDING)

    chunk_texts = [c['text'] for c in chunks]
    # Wrap blocking OpenAI call
    embeddings = await asyncio.to_thread(embed_texts, chunk_texts)

    # Stage: Saving
    await tracker.update_task(item_key, stage=TaskStage.SAVING)

    # Delete existing data if reindexing
    if force_reindex:
        await asyncio.to_thread(delete_paper, item_key)

    # Insert paper metadata
    authors = format_authors(item_data.get('creators', []))
    year = None
    date_str = item_data.get('date', '')
    if date_str and len(date_str) >= 4:
        try:
            year = int(date_str[:4])
        except ValueError:
            pass

    await asyncio.to_thread(
        insert_paper,
        item_key=item_key,
        citation_key=citation_key,
        title=title,
        authors=authors,
        year=year,
        project=project,
        pdf_path=str(pdf_path),
        total_chunks=len(chunks),
    )

    # Batch insert all chunks with embeddings (single DB call)
    await asyncio.to_thread(
        insert_chunks_batch,
        item_key=item_key,
        chunks=chunks,
        embeddings=embeddings,
    )

    return {'status': 'indexed', 'chunks': len(chunks)}


async def _index_single_paper(
    item_data: dict,
    project_path: Path,
    project: str,
    force_reindex: bool,
) -> dict:
    """Index a single paper."""
    item_key = item_data.get('key')
    citation_key = get_citation_key_from_extra(item_data.get('extra', ''))
    title = item_data.get('title', 'Untitled')

    # Check if already indexed
    if not force_reindex and paper_exists(item_key):
        return {'status': 'skipped', 'reason': 'Already indexed'}

    # Find PDF file
    pdf_path = None
    if citation_key:
        candidate = project_path / f"{citation_key}.pdf"
        if candidate.exists():
            pdf_path = candidate

    # If no citation key in Extra, try to generate one from metadata
    if not pdf_path:
        authors = format_authors(item_data.get('creators', []))
        year = item_data.get('date', '')[:4] if item_data.get('date') else ''
        if title and authors and year:
            generated_key = generate_citation_key(title, authors, year)
            candidate = project_path / f"{generated_key}.pdf"
            if candidate.exists():
                citation_key = generated_key
                pdf_path = candidate

    if not pdf_path:
        return {'status': 'skipped', 'reason': 'No PDF found'}

    # Extract text with page breaks
    try:
        full_text, page_breaks = extract_pdf_text_with_pages(pdf_path)
    except Exception as e:
        return {'status': 'skipped', 'reason': f'PDF extraction failed: {e}'}

    if not full_text.strip():
        return {'status': 'skipped', 'reason': 'PDF has no extractable text'}

    # Chunk the text
    chunks = chunk_text(full_text, page_breaks=page_breaks)

    if not chunks:
        return {'status': 'skipped', 'reason': 'No chunks generated'}

    # Generate embeddings (batch for efficiency)
    chunk_texts = [c['text'] for c in chunks]
    embeddings = embed_texts(chunk_texts)

    # Delete existing data if reindexing
    if force_reindex:
        delete_paper(item_key)

    # Insert paper metadata
    authors = format_authors(item_data.get('creators', []))
    year = None
    date_str = item_data.get('date', '')
    if date_str and len(date_str) >= 4:
        try:
            year = int(date_str[:4])
        except ValueError:
            pass

    insert_paper(
        item_key=item_key,
        citation_key=citation_key,
        title=title,
        authors=authors,
        year=year,
        project=project,
        pdf_path=str(pdf_path),
        total_chunks=len(chunks),
    )

    # Insert chunks with embeddings
    for chunk, embedding in zip(chunks, embeddings):
        insert_chunk(
            item_key=item_key,
            chunk_index=chunk['chunk_index'],
            page_number=chunk['page_number'],
            text=chunk['text'],
            embedding=embedding,
        )

    return {'status': 'indexed', 'chunks': len(chunks)}


async def search_papers(
    query: str,
    project: Optional[str] = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """
    Semantic search across indexed paper PDFs.

    Uses OpenAI embeddings and DuckDB vector similarity search
    to find relevant passages.

    Args:
        query: Natural language search query
        project: Limit to specific project (optional)
        max_results: Maximum results to return (default 10, max 50)

    Returns:
        {
            success: bool,
            query: str,
            results: [{citation_key, title, authors, year, page_number, text, score}]
        }
    """
    try:
        # Validate max_results
        max_results = min(max(1, max_results), 50)

        # Validate project if provided
        if project:
            config = config_manager.load()
            if project not in config.projects:
                return {
                    'success': False,
                    'error': {
                        'code': 'PROJECT_NOT_FOUND',
                        'message': f"Project '{project}' not found"
                    }
                }

        # Initialize connection
        get_connection()

        # Generate query embedding
        query_embedding = embed_query(query)

        # Search for similar chunks
        results = search_similar(
            query_embedding=query_embedding,
            project=project,
            max_results=max_results,
        )

        return {
            'success': True,
            'query': query,
            'count': len(results),
            'results': results,
        }

    except EmbeddingError as e:
        return {
            'success': False,
            'error': {
                'code': 'EMBEDDING_ERROR',
                'message': str(e)
            }
        }
    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SEARCH_ERROR',
                'message': str(e)
            }
        }


async def ask_papers(
    question: str,
    project: Optional[str] = None,
    max_passages: int = 10,
) -> dict[str, Any]:
    """
    Ask a question about your literature.

    Searches indexed papers and returns relevant passages with coverage
    metadata and synthesis instructions. Claude Code synthesizes the answer,
    with guidance to honestly assess whether the literature adequately
    addresses the question.

    Args:
        question: Natural language question about your papers
        project: Limit to specific project (optional)
        max_passages: Number of relevant passages to include (default 10, max 20)

    Returns:
        {
            success: bool,
            question: str,
            context: str,  # Formatted passages with synthesis instructions
            coverage: {passages_found, unique_papers, scores: {min, max, mean}},
            sources: [{citation_key, title, authors, year, page, score}]
        }
    """
    try:
        # Validate max_passages
        max_passages = min(max(1, max_passages), 20)

        # Use search_papers to get relevant passages
        search_result = await search_papers(
            query=question,
            project=project,
            max_results=max_passages,
        )

        if not search_result['success']:
            return search_result

        results = search_result.get('results', [])

        if not results:
            return {
                'success': True,
                'question': question,
                'context': "No relevant passages found in your indexed papers. Make sure papers are indexed using index_papers first.",
                'coverage': {'passages_found': 0, 'unique_papers': 0, 'scores': None},
                'sources': [],
            }

        # Calculate coverage metadata
        unique_papers = len(set(r['citation_key'] for r in results))
        scores = [r['score'] for r in results]
        coverage = {
            'passages_found': len(results),
            'unique_papers': unique_papers,
            'scores': {
                'min': round(min(scores), 4),
                'max': round(max(scores), 4),
                'mean': round(sum(scores) / len(scores), 4),
            }
        }

        # Build context with passages and synthesis instructions
        context_parts = []

        # Add project context if available
        if project:
            project_context = get_context_text(project)
            if project_context:
                context_parts.append(f"## Project Context\n{project_context}\n\n---\n")

        # Question
        context_parts.append(f"## Question\n{question}\n\n")

        # Coverage summary (helps model reason about adequacy)
        context_parts.append(
            f"## Literature Coverage\n"
            f"Found {coverage['passages_found']} passages from {coverage['unique_papers']} papers. "
            f"Similarity scores: {coverage['scores']['min']:.2f} to {coverage['scores']['max']:.2f} "
            f"(mean: {coverage['scores']['mean']:.2f}).\n\n"
        )

        # Passages
        context_parts.append("## Relevant Passages\n")
        for i, r in enumerate(results, 1):
            citation = r['citation_key']
            if r['page_number']:
                citation += f", p.{r['page_number']}"

            context_parts.append(
                f"\n[{i}] {r['title']} ({citation}):\n"
                f'"{r["text"]}"\n'
            )

        # Synthesis instructions
        context_parts.append("""
---

## Synthesis Instructions

Based on these passages, provide a thoughtful response to the question.

**Important:** Before synthesizing, consider whether this literature actually addresses the question well:
- Do these passages directly address the question, or are they tangentially related?
- Is the topic well-covered (multiple papers, different perspectives) or thinly covered?
- Are there aspects of the question that none of the passages address?

If coverage is limited or incomplete:
- Be honest about what the passages do and don't address
- Provide the best answer from what's available, but note limitations naturally
- Suggest specific follow-up searches (search terms, databases like PubMed/Semantic Scholar/Consensus)

If coverage is good:
- Synthesize across sources, noting agreements and any tensions
- Cite sources using the citation keys

Write in a natural, reasoning tone. Avoid formulaic language - reason authentically about the coverage and answer.
""")

        # Add project context reminder if present
        if project and get_context_text(project):
            context_parts.append(
                "\nTailor your response to the project's goal, audience, and style.\n"
            )

        # Build sources list
        sources = [
            {
                'citation_key': r['citation_key'],
                'title': r['title'],
                'authors': r['authors'],
                'year': r['year'],
                'page': r['page_number'],
                'score': r['score'],
            }
            for r in results
        ]

        return {
            'success': True,
            'question': question,
            'context': ''.join(context_parts),
            'coverage': coverage,
            'sources': sources,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'ASK_ERROR',
                'message': str(e)
            }
        }


async def rag_status(project: Optional[str] = None) -> dict[str, Any]:
    """
    Get RAG index status and statistics.

    Args:
        project: Limit to specific project (optional)

    Returns:
        {
            success: bool,
            stats: {total_papers, total_chunks, papers_by_project},
            indexed_papers: [{item_key, citation_key, title, total_chunks, indexed_at}]
        }
    """
    try:
        get_connection()

        stats = get_stats()
        papers = get_indexed_papers(project=project)

        return {
            'success': True,
            'stats': stats,
            'indexed_papers': papers,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'STATUS_ERROR',
                'message': str(e)
            }
        }
