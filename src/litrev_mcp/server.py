"""
MCP server entry point for litrev-mcp.

This module initializes the MCP server and registers all tools.
"""

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from litrev_mcp.config import (
    config_manager,
    get_zotero_api_key,
    get_zotero_user_id,
)
from litrev_mcp.tools.zotero import (
    zotero_list_projects,
    zotero_create_collection,
    zotero_add_paper,
    zotero_delete_paper,
    zotero_update_status,
    zotero_get_by_status,
    zotero_search,
    zotero_get_citation_key,
)
from litrev_mcp.tools.pubmed import pubmed_search
from litrev_mcp.tools.semantic_scholar import (
    semantic_scholar_search,
    semantic_scholar_references,
    semantic_scholar_citations,
)
from litrev_mcp.tools.eric import eric_search
from litrev_mcp.tools.insights import (
    save_insight,
    search_insights,
    analyze_insights,
    list_insights,
)
from litrev_mcp.tools.status import (
    project_status,
    pending_actions,
)
from litrev_mcp.tools.setup import (
    setup_check,
    setup_create_project,
)
from litrev_mcp.tools.pdf import process_pdf_inbox, migrate_zotero_attachments
from litrev_mcp.tools.rag import (
    index_papers,
    search_papers,
    ask_papers,
    rag_status,
    generate_index_script,
)
from litrev_mcp.tools.context import (
    get_project_context,
    update_project_context,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create the MCP server instance
server = Server("litrev-mcp")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available tools."""
    return [
        Tool(
            name="litrev_hello",
            description="Test tool to verify litrev-mcp is working. Returns configuration status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        # Zotero tools
        Tool(
            name="zotero_list_projects",
            description="List all Zotero collections (projects) with paper counts by status.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="zotero_create_collection",
            description="Create a new Zotero collection. Returns the collection key to link with a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the new collection",
                    },
                    "parent_key": {
                        "type": "string",
                        "description": "Parent collection key for nested collections (optional)",
                    },
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="zotero_add_paper",
            description="Add a paper to Zotero by DOI or manual metadata. Automatically tags with _needs-pdf. Returns citation key for PDF naming.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MEAS-ERR')",
                    },
                    "doi": {
                        "type": "string",
                        "description": "DOI - if provided, used for metadata",
                    },
                    "title": {
                        "type": "string",
                        "description": "Paper title (required if no DOI)",
                    },
                    "authors": {
                        "type": "string",
                        "description": "Authors (if no DOI)",
                    },
                    "year": {
                        "type": "integer",
                        "description": "Publication year (if no DOI)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Where this was found (e.g., 'PubMed', 'Consensus')",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="zotero_delete_paper",
            description="Delete a paper from Zotero. CAUTION: Permanent deletion requires confirm=True.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": "Zotero item key",
                    },
                    "doi": {
                        "type": "string",
                        "description": "Paper DOI",
                    },
                    "title_search": {
                        "type": "string",
                        "description": "Search by title fragment",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to proceed with deletion",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="zotero_update_status",
            description="Update the status tag on a paper. Provide item_key, doi, or title_search to identify the paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "new_status": {
                        "type": "string",
                        "enum": ["needs_pdf", "needs_notebooklm", "complete"],
                        "description": "New status for the paper",
                    },
                    "item_key": {
                        "type": "string",
                        "description": "Zotero item key",
                    },
                    "doi": {
                        "type": "string",
                        "description": "Paper DOI",
                    },
                    "title_search": {
                        "type": "string",
                        "description": "Search by title fragment",
                    },
                },
                "required": ["new_status"],
            },
        ),
        Tool(
            name="zotero_get_by_status",
            description="Get papers filtered by status within a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["needs_pdf", "needs_notebooklm", "complete", "all"],
                        "description": "Status to filter by",
                    },
                },
                "required": ["project", "status"],
            },
        ),
        Tool(
            name="zotero_search",
            description="Search within your Zotero library. Returns papers with citation keys.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="zotero_get_citation_key",
            description="Get Better BibTeX citation key(s) for paper(s). Useful when writing and you need the cite key.",
            inputSchema={
                "type": "object",
                "properties": {
                    "item_key": {
                        "type": "string",
                        "description": "Zotero item key",
                    },
                    "doi": {
                        "type": "string",
                        "description": "Paper DOI",
                    },
                    "title_search": {
                        "type": "string",
                        "description": "Search by title fragment (may return multiple)",
                    },
                },
                "required": [],
            },
        ),
        # Search API tools
        Tool(
            name="pubmed_search",
            description="Search PubMed for biomedical papers. Supports PubMed query syntax.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (supports PubMed syntax)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10, max 50)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="semantic_scholar_search",
            description="Search Semantic Scholar for academic papers across all fields. Returns citation counts and S2 paper IDs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10, max 100)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="semantic_scholar_references",
            description="Backward snowball: get papers cited BY a given paper. Useful for finding foundational work.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "DOI, S2 paper ID, or PMID (e.g., '10.1234/example', 'PMID:12345678')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum references to return (default 50)",
                        "default": 50,
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="semantic_scholar_citations",
            description="Forward snowball: get papers that CITE a given paper. Useful for finding recent work building on this paper.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "string",
                        "description": "DOI, S2 paper ID, or PMID (e.g., '10.1234/example', 'PMID:12345678')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum citations to return (default 50)",
                        "default": 50,
                    },
                },
                "required": ["paper_id"],
            },
        ),
        Tool(
            name="eric_search",
            description="Search ERIC (Education Resources Information Center) for education research papers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10, max 50)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
        # Insights tools
        Tool(
            name="save_insight",
            description="Save a Consensus summary, NotebookLM answer, or synthesis note to the project's knowledge base. Can optionally extract DOIs and add referenced papers to Zotero.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MEAS-ERR')",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["consensus", "notebooklm", "synthesis", "reading_notes"],
                        "description": "Source type of the insight",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Brief descriptor (becomes part of filename)",
                    },
                    "content": {
                        "type": "string",
                        "description": "The actual content to save",
                    },
                    "query": {
                        "type": "string",
                        "description": "Original question that prompted this (optional)",
                    },
                    "papers_referenced": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of citation keys mentioned (optional)",
                    },
                    "add_references_to_zotero": {
                        "type": "boolean",
                        "description": "If true, extract DOIs from content and add new papers to Zotero (default false)",
                        "default": False,
                    },
                },
                "required": ["project", "source", "topic", "content"],
            },
        ),
        Tool(
            name="search_insights",
            description="Search saved insights and return content for synthesis. Searches across all saved notes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query or question",
                    },
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["consensus", "notebooklm", "synthesis", "reading_notes"],
                        "description": "Filter by source type (optional)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="analyze_insights",
            description="Analyze insights to answer a question, compare sources, or detect tensions/contradictions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer or analyze",
                    },
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["answer", "compare", "tensions"],
                        "description": "Analysis mode (default: answer)",
                        "default": "answer",
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="list_insights",
            description="List all saved insights for a project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["consensus", "notebooklm", "synthesis", "reading_notes"],
                        "description": "Filter by source type (optional)",
                    },
                },
                "required": ["project"],
            },
        ),
        # Status & Dashboard tools
        Tool(
            name="project_status",
            description="Get a comprehensive dashboard view of a project including paper counts, insights stats, and recent activity.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MEAS-ERR')",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="pending_actions",
            description="Get all pending user actions across projects (PDFs to acquire, papers to add to NotebookLM). Includes complete information for both Zotero and Google Drive operations.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        # Setup Wizard tools
        Tool(
            name="setup_check",
            description="Check if litrev-mcp is properly configured. Verifies Google Drive, Literature folder, config file, and Zotero credentials.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="setup_create_project",
            description="Create a new literature review project with directory structure and config entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Short project code (e.g., 'MEAS-ERR')",
                    },
                    "name": {
                        "type": "string",
                        "description": "Full project name",
                    },
                    "zotero_collection_key": {
                        "type": "string",
                        "description": "Zotero collection key (optional, can add later)",
                    },
                },
                "required": ["code", "name"],
            },
        ),
        # PDF Processing tools
        Tool(
            name="process_pdf_inbox",
            description="Process PDFs in a project's to_add/ folder. Matches them to existing Zotero entries, renames with citation keys, and updates status. Returns unmatched PDFs for interactive review.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'TEST')",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="migrate_zotero_attachments",
            description="Migrate PDFs stored on Zotero's servers to Google Drive. Downloads server-stored attachments, saves to Drive folder with citation key naming, adds Drive link to Zotero, and deletes original. Useful for papers added by drag-drop.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'TEST')",
                    },
                },
                "required": ["project"],
            },
        ),
        # RAG (Literature Search) tools
        Tool(
            name="index_papers",
            description="Index PDFs from a project for semantic search. Extracts text, chunks it, generates OpenAI embeddings, and stores in DuckDB. Opens a browser-based progress dashboard. Run this before using search_papers or ask_papers.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MI-IC')",
                    },
                    "force_reindex": {
                        "type": "boolean",
                        "description": "If true, reindex papers even if already indexed (default false)",
                        "default": False,
                    },
                    "show_progress": {
                        "type": "boolean",
                        "description": "If true, open browser-based progress dashboard (default true)",
                        "default": True,
                    },
                    "max_concurrent": {
                        "type": "integer",
                        "description": "Maximum papers to process in parallel (default 5)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="search_papers",
            description="Semantic search across indexed paper PDFs. Returns relevant passages with citation keys and page numbers. Use index_papers first to build the index.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query",
                    },
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 10, max 50)",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="ask_papers",
            description="Ask a question about your literature. Searches indexed papers and returns relevant passages formatted with citations for synthesis. Use this for questions like 'Is there support for X in my literature?'",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Natural language question about your papers",
                    },
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                    "max_passages": {
                        "type": "integer",
                        "description": "Number of relevant passages to include (default 5, max 20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["question"],
            },
        ),
        Tool(
            name="rag_status",
            description="Get RAG index status and statistics. Shows which papers are indexed and chunk counts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Limit to specific project (optional)",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="generate_index_script",
            description="Generate a standalone Python script for indexing papers. Recommended for large collections to avoid MCP timeout.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MI-IC')",
                    },
                    "force_reindex": {
                        "type": "boolean",
                        "description": "If true, script will reindex all papers",
                        "default": False,
                    },
                },
                "required": ["project"],
            },
        ),
        # Project Context tools
        Tool(
            name="get_project_context",
            description="Get project context (goal, audience, style) from _context.md. Returns template if none exists. Use /init-litrev-context skill to set up context collaboratively.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MI-IC')",
                    },
                },
                "required": ["project"],
            },
        ),
        Tool(
            name="update_project_context",
            description="Create or update project context file (_context.md). Stores goal, audience, style, and key questions to tailor future responses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Project code (e.g., 'MI-IC')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full markdown content for _context.md",
                    },
                },
                "required": ["project", "content"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    if name == "litrev_hello":
        return await handle_hello()

    # Zotero tools
    if name == "zotero_list_projects":
        result = await zotero_list_projects()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_create_collection":
        result = await zotero_create_collection(
            name=arguments.get("name"),
            parent_key=arguments.get("parent_key"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_add_paper":
        result = await zotero_add_paper(
            project=arguments.get("project"),
            doi=arguments.get("doi"),
            title=arguments.get("title"),
            authors=arguments.get("authors"),
            year=arguments.get("year"),
            source=arguments.get("source"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_delete_paper":
        result = await zotero_delete_paper(
            item_key=arguments.get("item_key"),
            doi=arguments.get("doi"),
            title_search=arguments.get("title_search"),
            confirm=arguments.get("confirm", False),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_update_status":
        result = await zotero_update_status(
            new_status=arguments.get("new_status"),
            item_key=arguments.get("item_key"),
            doi=arguments.get("doi"),
            title_search=arguments.get("title_search"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_get_by_status":
        result = await zotero_get_by_status(
            project=arguments.get("project"),
            status=arguments.get("status"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_search":
        result = await zotero_search(
            query=arguments.get("query"),
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "zotero_get_citation_key":
        result = await zotero_get_citation_key(
            item_key=arguments.get("item_key"),
            doi=arguments.get("doi"),
            title_search=arguments.get("title_search"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Search API tools
    if name == "pubmed_search":
        result = await pubmed_search(
            query=arguments.get("query"),
            max_results=arguments.get("max_results", 10),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "semantic_scholar_search":
        result = await semantic_scholar_search(
            query=arguments.get("query"),
            max_results=arguments.get("max_results", 10),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "semantic_scholar_references":
        result = await semantic_scholar_references(
            paper_id=arguments.get("paper_id"),
            max_results=arguments.get("max_results", 50),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "semantic_scholar_citations":
        result = await semantic_scholar_citations(
            paper_id=arguments.get("paper_id"),
            max_results=arguments.get("max_results", 50),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "eric_search":
        result = await eric_search(
            query=arguments.get("query"),
            max_results=arguments.get("max_results", 10),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Insights tools
    if name == "save_insight":
        result = await save_insight(
            project=arguments.get("project"),
            source=arguments.get("source"),
            topic=arguments.get("topic"),
            content=arguments.get("content"),
            query=arguments.get("query"),
            papers_referenced=arguments.get("papers_referenced"),
            add_references_to_zotero=arguments.get("add_references_to_zotero", False),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "search_insights":
        result = await search_insights(
            query=arguments.get("query"),
            project=arguments.get("project"),
            source=arguments.get("source"),
            max_results=arguments.get("max_results", 10),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "analyze_insights":
        result = await analyze_insights(
            question=arguments.get("question"),
            project=arguments.get("project"),
            mode=arguments.get("mode", "answer"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "list_insights":
        result = await list_insights(
            project=arguments.get("project"),
            source=arguments.get("source"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Status & Dashboard tools
    if name == "project_status":
        result = await project_status(
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "pending_actions":
        result = await pending_actions()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Setup Wizard tools
    if name == "setup_check":
        result = await setup_check()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "setup_create_project":
        result = await setup_create_project(
            code=arguments.get("code"),
            name=arguments.get("name"),
            zotero_collection_key=arguments.get("zotero_collection_key"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # PDF Processing tools
    if name == "process_pdf_inbox":
        result = await process_pdf_inbox(
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "migrate_zotero_attachments":
        result = await migrate_zotero_attachments(
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # RAG (Literature Search) tools
    if name == "index_papers":
        result = await index_papers(
            project=arguments.get("project"),
            force_reindex=arguments.get("force_reindex", False),
            show_progress=arguments.get("show_progress", True),
            max_concurrent=arguments.get("max_concurrent", 5),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "search_papers":
        result = await search_papers(
            query=arguments.get("query"),
            project=arguments.get("project"),
            max_results=arguments.get("max_results", 10),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "ask_papers":
        result = await ask_papers(
            question=arguments.get("question"),
            project=arguments.get("project"),
            max_passages=arguments.get("max_passages", 5),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "rag_status":
        result = await rag_status(
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "generate_index_script":
        result = await generate_index_script(
            project=arguments.get("project"),
            force_reindex=arguments.get("force_reindex", False),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    # Project Context tools
    if name == "get_project_context":
        result = await get_project_context(
            project=arguments.get("project"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "update_project_context":
        result = await update_project_context(
            project=arguments.get("project"),
            content=arguments.get("content"),
        )
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def handle_hello() -> list[TextContent]:
    """Handle the hello test tool."""
    status_lines = ["litrev-mcp is running!", ""]
    
    # Check Google Drive
    drive_path = config_manager.drive_path
    if drive_path:
        status_lines.append(f"✓ Google Drive: {drive_path}")
    else:
        status_lines.append("✗ Google Drive: not detected")
    
    # Check Literature folder
    lit_path = config_manager.literature_path
    if lit_path and lit_path.exists():
        status_lines.append(f"✓ Literature folder: {lit_path}")
    elif lit_path:
        status_lines.append(f"✗ Literature folder: {lit_path} (does not exist)")
    else:
        status_lines.append("✗ Literature folder: not configured")
    
    # Check config file
    config_path = config_manager.config_path
    if config_path and config_path.exists():
        status_lines.append(f"✓ Config file: {config_path}")
        config = config_manager.load()
        project_count = len(config.projects)
        status_lines.append(f"  Projects defined: {project_count}")
    elif config_path:
        status_lines.append(f"✗ Config file: {config_path} (does not exist)")
    else:
        status_lines.append("✗ Config file: not configured")
    
    # Check Zotero credentials
    status_lines.append("")
    zotero_key = get_zotero_api_key()
    zotero_user = get_zotero_user_id()
    
    if zotero_key:
        status_lines.append(f"✓ ZOTERO_API_KEY: set ({len(zotero_key)} chars)")
    else:
        status_lines.append("✗ ZOTERO_API_KEY: not set")
    
    if zotero_user:
        status_lines.append(f"✓ ZOTERO_USER_ID: {zotero_user}")
    else:
        status_lines.append("✗ ZOTERO_USER_ID: not set")
    
    return [TextContent(type="text", text="\n".join(status_lines))]


async def run_server():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main():
    """Main entry point."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
