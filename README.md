# litrev-mcp

MCP server for AI-assisted literature review with Zotero, PubMed, Semantic Scholar, and argument mapping.

## Overview

An MCP (Model Context Protocol) server that provides literature review tools to Claude. Enables systematic literature discovery, retrieval, and organization with Zotero as the central repository. Supports PubMed, Semantic Scholar, and ERIC searches, citation snowballing, a local knowledge base for insights, and an argument map that builds a knowledge graph from your literature with semantic search and intelligent graph traversal.

## Status

✅ **v0.5.0-beta - Argument Map with GraphRAG Search**

- 61 tools across 12 categories
- Full Zotero integration
- Search APIs (PubMed, Semantic Scholar, ERIC)
- Knowledge base system
- Semantic search over your PDFs (MotherDuck cloud DuckDB + OpenAI embeddings)
- **Argument Map (beta)** - Build a knowledge graph from your literature with propositions, relationships, evidence, and topics
- **GraphRAG Search (beta)** - Semantic search over your argument map with LLM-judged graph traversal
- AI-powered extraction, keyword and GraphRAG search, gap detection, and interactive visualization
- Issue tracking for argument map maintenance
- Project context for tailored responses (goal, audience, style)
- Claude-powered synthesis with coverage assessment
- Project dashboard and setup wizard

## Features

### Zotero Integration (10 tools)
- `zotero_list_projects` - List collections with paper counts by status
- `zotero_create_collection` - Create a new Zotero collection
- `zotero_add_paper` - Add papers by DOI or manual entry (automatically fetches metadata from CrossRef)
- `zotero_delete_paper` - Delete papers from Zotero (requires confirmation)
- `zotero_update_status` - Change status tags (_needs-pdf, _needs-notebooklm, _complete)
- `zotero_get_by_status` - Filter papers by status
- `zotero_search` - Search your library
- `zotero_get_citation_key` - Get Better BibTeX citation keys
- `process_pdf_inbox` - Process PDFs in to_add folder, match to Zotero entries, rename and organize
- `migrate_zotero_attachments` - Migrate server-stored PDFs to Google Drive with link attachments

### Literature Search (5 tools)
- `pubmed_search` - Search PubMed for biomedical papers
- `semantic_scholar_search` - Search Semantic Scholar across all fields
- `semantic_scholar_references` - Backward snowball (papers cited BY a paper)
- `semantic_scholar_citations` - Forward snowball (papers that CITE a paper)
- `eric_search` - Search ERIC for education research

### Knowledge Base (4 tools)
- `save_insight` - Save Consensus/NotebookLM summaries and notes; optionally extract DOIs and add papers to Zotero (with CrossRef metadata)
- `search_insights` - Search saved insights by keyword
- `analyze_insights` - Answer questions from saved insights
- `list_insights` - List all insights for a project

### RAG Literature Search (5 tools)
- `index_papers` - Index PDFs for semantic search (extracts text, chunks, generates OpenAI embeddings). Note: May timeout on large collections; use `generate_index_script` instead
- `generate_index_script` - Generate a standalone Python script for indexing papers. Recommended for large collections to avoid MCP timeout
- `search_papers` - Semantic search across indexed papers, returns passages with citations
- `ask_papers` - Ask questions about your literature; uses Claude to synthesize a reasoned answer with honest assessment of coverage adequacy and recommendations for follow-up searches when gaps exist
- `rag_status` - View indexing status and statistics

### Status & Dashboard (2 tools)
- `project_status` - Get comprehensive project dashboard
- `pending_actions` - Get all pending user actions (PDFs to acquire, papers for NotebookLM)

### Setup Wizard (3 tools)
- `setup_check` - Verify configuration (Google Drive, Zotero credentials)
- `setup_create_project` - Create new project with directory structure
- `gdrive_reauthenticate` - Force re-authentication with Google Drive (use when tokens expire)

### Project Context (2 tools)
- `get_project_context` - Get project context (goal, audience, style) from _context.md
- `update_project_context` - Create or update project context file

Use `/init-litrev-context PROJECT` skill for collaborative context setup.

### Workflow Tools (5 tools)
- `save_gap` - Document research gaps (what you're searching for)
- `save_session_log` - Log end-of-session summaries for audit trail
- `save_pivot` - Track conceptual shifts and understanding changes
- `save_search_strategy` - Record search strategies for reproducibility
- `get_workflow_status` - View workflow metrics (gaps, pivots, searches, phases)

**NEW in v0.3.0**: Automatic workflow templates (`_workflow.md`, `_synthesis_notes.md`, `_gaps.md`, `_pivots.md`, `_searches.md`) created for new projects. Proactive guidance built into all tool outputs to follow best practices. See `todo/litrev_mcp_best_practices.md` for the structured workflow approach.

### Argument Map (23 tools) — BETA

> **Note:** The argument map and GraphRAG search features are in beta. Tool names, schemas, and database tables may change in future releases. Feedback welcome via [GitHub Issues](https://github.com/marcus-waldman/litrev_mcp/issues).

Build a living knowledge graph from your literature. The argument map organizes propositions (arguable assertions), relationships between them, and evidence from your papers — distinguishing between:
- **Grounded propositions** (extracted from your papers with evidence)
- **AI scaffolding** (structural knowledge from Claude's general knowledge)
- **Gaps** (salient propositions without literature support)

#### Extraction & Core (7 tools):
- `extract_concepts` - **AI extraction with Claude Opus 4.5** - Automatically extracts propositions, topics, relationships, and evidence from saved insights
- `add_propositions` - Add propositions, topics, relationships, and evidence to the map (after extraction or manual entry)
- `show_argument_map` - View argument map structure with statistics and details
- `update_proposition` - Modify definitions, relationships, or evidence
- `delete_proposition` - Remove propositions from project
- `delete_relationship` - Delete a specific relationship between propositions
- `query_propositions` - **Keyword search** - Find propositions matching your query by keyword. For semantic search, use `search_argument_map`

#### Topics (5 tools):
Organize propositions into high-level themes (e.g., "Measurement Error Problem", "Bayesian Estimation"):
- `create_topic` / `list_topics` / `update_topic` / `delete_topic` - CRUD for topics
- `assign_proposition_topic` - Link propositions to topics (primary or secondary)

#### Discovery & Visualization (2 tools):
- `find_argument_gaps` - **Gap detection** - Identify AI scaffolding propositions that lack grounded evidence, with suggestions for literature searches
- `visualize_argument_map` - **Interactive PyVis graph** - Generate HTML visualization with color coding (green=grounded, yellow=scaffolding, red=gaps), node size by evidence count, rich tooltips, and directed edges

#### Conflicts & Issues (6 tools):
- `list_conflicts` / `resolve_conflict` - View and resolve contradictions between AI scaffolding and grounded evidence
- `add_proposition_issue` / `list_proposition_issues` / `resolve_proposition_issue` / `delete_proposition_issue` - Track needed changes (needs_evidence, rephrase, wrong_topic, merge, split, etc.)

#### GraphRAG Search (3 tools):
Semantic search over your argument map with intelligent graph traversal — instead of loading the entire graph, find exactly the relevant subgraph:
- `embed_propositions` - Generate embeddings for propositions (run once, then incrementally)
- `search_argument_map` - **Semantic search + LLM-judged traversal** - Find propositions similar to your query via vector similarity, then Claude Sonnet decides how deep and which relationship types to follow for subgraph expansion
- `expand_argument_map` - Manually expand from specific propositions along relationships (no LLM, direct control)

**Database**: 10 tables in MotherDuck cloud (default database: `litrev`) — RAG (papers, chunks, rag_metadata) + Argument Map (propositions, aliases, project_propositions, relationships, evidence, conflicts, proposition_embeddings)

**Epistemic Tagging**: Every proposition and relationship marked as either `insight` (from literature) or `ai_knowledge` (from Claude's general knowledge, could be wrong).

### Test Tool (1 tool)
- `litrev_hello` - Verify litrev-mcp is working

## Prerequisites

Before installing litrev-mcp, ensure you have:

### Required for All Features

- **Python 3.10+** ([Download](https://www.python.org/downloads/))
- **Zotero desktop application** ([Download](https://www.zotero.org/download/))
- **Better BibTeX plugin for Zotero** ([Installation guide](#better-bibtex-setup))
- **Google Drive** (mounted/synced to your computer)
- **Zotero API Key & User ID** ([How to get them](#zotero-credentials))

### Required for RAG Literature Search

- **OpenAI API Key** ([Get one](https://platform.openai.com/api-keys))
  - Used for `index_papers`, `search_papers`, `ask_papers`
  - Costs: ~$0.10-0.50 per paper indexed, ~$0.001 per search

### Required for Argument Map

- **Anthropic API Key** ([Get one](https://console.anthropic.com/settings/keys))
  - Used for `extract_concepts` (Claude Opus 4.5) and `search_argument_map` (Claude Sonnet for traversal judgment)
  - Costs: ~$0.03-0.10 per insight extraction, ~$0.003 per search traversal

### Optional (Improves Performance)

- **NCBI API Key** - Increases PubMed rate limits (3→10 req/sec)
- **Semantic Scholar API Key** - Increases S2 rate limits (100→5000 req/5min)

### Better BibTeX Setup

Better BibTeX is **required** (not optional) for litrev-mcp to work.

1. In Zotero, go to **Tools → Add-ons**
2. Click the gear icon → **Install Add-on From File...**
3. Download and select the [Better BibTeX .xpi file](https://retorque.re/zotero-better-bibtex/installation/)
4. Restart Zotero

**Verify installation:**
- Go to **Zotero → Preferences → Better BibTeX**
- You should see the Better BibTeX settings panel

If Better BibTeX is missing, you'll see errors like `citation key not found`.

### Zotero Credentials

You need both an API Key and User ID:

**Get your API Key:**
1. Go to [https://www.zotero.org/settings/keys](https://www.zotero.org/settings/keys)
2. Click **Create new private key**
3. Name: "litrev-mcp"
4. Permissions: Check "Allow library access" and "Allow write access"
5. Click **Save Key**
6. Copy the generated key (you won't see it again)

**Find your User ID:**
- It's shown at the top of the same page: "Your userID for use in API calls is **1234567**"
- Or in your Zotero profile URL: `https://www.zotero.org/USERNAME` → Settings → Feeds/API shows the numeric ID

### Google Drive Folder Setup

litrev-mcp stores PDFs and config in Google Drive for sync across machines.

**1. Create the Literature folder:**

<details>
<summary><b>macOS</b></summary>

```bash
mkdir -p ~/Library/CloudStorage/GoogleDrive-*/My\ Drive/Literature
```
</details>

<details>
<summary><b>Linux</b></summary>

```bash
mkdir -p ~/google-drive/Literature
```
</details>

<details>
<summary><b>Windows</b></summary>

Open File Explorer and create:
- `G:\My Drive\Literature` (if G: is your Google Drive)
- OR `C:\Users\YourName\Google Drive\Literature` (depends on your setup)

To find your Google Drive location, right-click the Google Drive icon in your system tray.
</details>

**2. litrev-mcp will auto-create:**
- `Literature/.litrev/` - Config folder
- `Literature/.litrev/config.yaml` - Main config file

**Database:** All RAG and argument map data is stored in MotherDuck cloud (default database: `litrev`). The database is automatically created on first connection and syncs across all machines — no need to rebuild indexes when switching machines.

**What syncs across machines:**
| Item | Syncs? | Location |
|------|--------|----------|
| Config file | ✅ Yes | `Literature/.litrev/config.yaml` |
| PDFs | ✅ Yes | `Literature/{PROJECT}/` |
| Notes | ✅ Yes | `Literature/{PROJECT}/_notes/` |
| Database | ✅ Yes (cloud) | MotherDuck (`litrev` database) |
| Environment vars | ❌ No (per-machine) | `~/.bashrc` or `~/.zshrc` |

### Environment Variables Setup

⚠️ **CRITICAL:** The three API keys below must be set as **persistent system/user environment variables** (not just in your shell). The MCP server runs as a separate process and cannot access shell-only variables.

**Required:**
- `ZOTERO_API_KEY` - Your Zotero API key (from https://www.zotero.org/settings/keys)
- `ZOTERO_USER_ID` - Your numeric Zotero User ID (from same page)
- `OPENAI_API_KEY` - Your OpenAI API key (from https://platform.openai.com/api-keys)
- `MOTHERDUCK_TOKEN` - Your MotherDuck token (from https://app.motherduck.com/settings)

**Optional:**
- `NCBI_API_KEY` - For higher PubMed rate limits
- `SEMANTIC_SCHOLAR_API_KEY` - For higher Semantic Scholar rate limits
- `LITREV_DRIVE_PATH` - Override Google Drive auto-detection (useful on Windows)

#### Setting Environment Variables

<details>
<summary><b>Windows (PowerShell)</b></summary>

Open PowerShell as Administrator and run:

```powershell
[Environment]::SetEnvironmentVariable("ZOTERO_API_KEY", "your-api-key-here", "User")
[Environment]::SetEnvironmentVariable("ZOTERO_USER_ID", "your-numeric-id", "User")
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "your-openai-key", "User")
[Environment]::SetEnvironmentVariable("MOTHERDUCK_TOKEN", "your-motherduck-token", "User")
```

**Verify:**
- Close all terminals and Claude Code
- Open a NEW PowerShell window
- Run: `$env:ZOTERO_API_KEY` - should show your key

If you're using Git Bash, you can also set them in `~/.bashrc`:
```bash
export ZOTERO_API_KEY="your-api-key-here"
export ZOTERO_USER_ID="your-numeric-id"
export OPENAI_API_KEY="your-openai-key"  # if using RAG
export ANTHROPIC_API_KEY="your-anthropic-key"  # if using argument map
```
Then close and reopen your terminal.

</details>

<details>
<summary><b>macOS</b></summary>

Add to your shell config file (`~/.zshrc` for newer macOS, `~/.bash_profile` for older):

```bash
export ZOTERO_API_KEY="your-api-key-here"
export ZOTERO_USER_ID="your-numeric-id"
export OPENAI_API_KEY="your-openai-key"  # if using RAG
export ANTHROPIC_API_KEY="your-anthropic-key"  # if using argument map
export MOTHERDUCK_TOKEN="your-motherduck-token"
```

Then:
```bash
source ~/.zshrc  # or ~/.bash_profile
# OR restart your terminal
```

**Verify:**
- Open a NEW terminal
- Run: `echo $ZOTERO_API_KEY` - should show your key

</details>

<details>
<summary><b>Linux</b></summary>

Add to your shell config file (`~/.bashrc` or `~/.zshrc`):

```bash
export ZOTERO_API_KEY="your-api-key-here"
export ZOTERO_USER_ID="your-numeric-id"
export OPENAI_API_KEY="your-openai-key"  # if using RAG
export ANTHROPIC_API_KEY="your-anthropic-key"  # if using argument map
export MOTHERDUCK_TOKEN="your-motherduck-token"
```

Then:
```bash
source ~/.bashrc  # or ~/.zshrc
# OR restart your terminal
```

**Verify:**
- Open a NEW terminal
- Run: `echo $ZOTERO_API_KEY` - should show your key

</details>

## Installation

### Quick Start

```bash
# Install using uv (recommended)
uv tool install git+https://github.com/yourusername/litrev-mcp.git

# Or using pip
pip install git+https://github.com/yourusername/litrev-mcp.git
```

### Development Install

```bash
# Clone the repository
git clone https://github.com/yourusername/litrev-mcp.git
cd litrev-mcp

# Create virtual environment and install
uv venv
source .venv/Scripts/activate  # Windows Git Bash
# or: source .venv/bin/activate  # macOS/Linux

# Install in development mode
uv pip install -e ".[dev]"

# Run tests
pytest
```

## Configuration

### 1. Set Environment Variables

⚠️ See the **[Environment Variables Setup](#environment-variables-setup)** section above for detailed platform-specific instructions. You need to set:
- `ZOTERO_API_KEY`
- `ZOTERO_USER_ID` (numeric)
- `OPENAI_API_KEY` (for RAG features)

### 2. Configure Claude Code

Add the MCP server to Claude Code:

```bash
claude mcp add litrev -- litrev-mcp
```

**Important:** You need to run this command **in every repository** where you want to use litrev-mcp. MCP servers are registered per-project. After the first setup, just navigate to each new project directory and run the same command.

### 3. Verify Setup

In Claude Code:
```
> Use setup_check to verify my configuration
```

### 4. Install Skill (Optional)

Copy the `/init-litrev-context` skill to your global Claude skills folder for collaborative project context setup:

```bash
# Create global skills folder if it doesn't exist
mkdir -p ~/.claude/skills

# Copy the skill
cp -r skills/init-litrev-context ~/.claude/skills/
```

Then restart Claude Code. Use `/init-litrev-context PROJECT` to collaboratively set up project context.

## Usage

### First-Time Setup

```
> Use setup_check to see if everything is configured

> Create a new project called "Measurement Error" with code "MEAS-ERR"
```

### Adding Papers

```
> Search PubMed for "glucose measurement error correction methods"

> Add this paper to my MEAS-ERR project: 10.1093/aje/kwj123

> What papers in MEAS-ERR need PDFs?
```

### Citation Snowballing

```
> Find papers that cite Carroll's measurement error book (DOI: 10.1201/9781420010138)

> Show me the key references from Fuller's 1987 paper
```

### Knowledge Base

```
> Save this Consensus summary about SIMEX to MEAS-ERR

> Search my insights for "regression calibration vs SIMEX"

> What have I learned about when to use SIMEX vs regression calibration?
```

### RAG Literature Search

```
> Index my MI-IC project for semantic search

> Search my papers for "AIC correction for missing data"

> Based on my literature, is there support for using FIML over multiple imputation?
```

### Project Context

```
> /init-litrev-context MI-IC

> Get the context for my MEAS-ERR project

> Update my MI-IC context to focus more on practical guidance for applied researchers
```

### Argument Map

```
> Extract concepts from the latest insight in MEAS-ERR

> Show the argument map for MEAS-ERR

> What propositions are most relevant to my Methods section for an epi journal?

> Find gaps in my MEAS-ERR argument map

> Visualize the argument map for MEAS-ERR
```

### Argument Map Search (GraphRAG)

```
> Embed the propositions for my ME-BLOOD project

> Search my ME-BLOOD argument map for "how does measurement error affect blood pressure estimates"

> Expand from these propositions to see supporting evidence
```

### Project Dashboard

```
> Show me the status of my MEAS-ERR project

> What are all my pending actions across projects?
```

## Directory Structure

```
Google Drive/
└── Literature/
    ├── .litrev/
    │   └── config.yaml          # Project configuration
    ├── MEAS-ERR/                # Project directory
    │   ├── _context.md          # Project context (goal, audience, style)
    │   ├── _concept_map.html    # Argument map visualization (auto-generated)
    │   ├── _workflow.md         # Phase-based progress tracking
    │   ├── _synthesis_notes.md  # Narrative synthesis skeleton
    │   ├── _gaps.md             # Gap documentation
    │   ├── _pivots.md           # Conceptual shift tracking
    │   ├── _searches.md         # Search reproducibility audit trail
    │   ├── _notes/              # Saved insights
    │   │   ├── 2024-01-15_consensus_simex_methods.md
    │   │   └── 2024-01-16_notebooklm_comparison.md
    │   ├── carroll_measurement_2006.pdf
    │   └── fuller_measurement_1987.pdf
    └── OTHER-PROJECT/
        └── ...
```

## Configuration File Format

`Literature/.litrev/config.yaml`:

```yaml
projects:
  MEAS-ERR:
    name: "Measurement Error Methods"
    zotero_collection_key: "ABC12345"
    drive_folder: "Literature/MEAS-ERR"
    notebooklm_notebooks:
      - "MEAS-ERR - Paper - Key Methods"

status_tags:
  needs_pdf: "_needs-pdf"
  needs_notebooklm: "_needs-notebooklm"
  complete: "_complete"

notebooklm_pattern: "{project_code} - {type} - {descriptor}"

better_bibtex:
  citation_key_pattern: "[auth:lower]_[shorttitle3_3:lower]_[year]"

# RAG configuration (optional)
rag:
  embedding_dimensions: 1536  # 256-1536, lower = smaller storage
```

### RAG Storage Optimization

The `embedding_dimensions` setting controls vector size for semantic search:

| Dimensions | Storage/chunk | Accuracy | Use case |
|------------|---------------|----------|----------|
| 1536 (default) | ~6 KB | Best | Small collections (<1000 papers) |
| 512 | ~2 KB | ~95% | Large collections |
| 256 | ~1 KB | ~90% | Very large collections |

**Note**: Changing dimensions requires deleting `literature.duckdb` and re-indexing.

## Workflow Example

1. **Search for papers**: Use PubMed, Semantic Scholar, or ERIC
2. **Add to Zotero**: Papers are automatically tagged `_needs-pdf`
3. **Acquire PDFs**: Download and name using citation key (e.g., `smith_glucose_2020.pdf`)
4. **Update status**: Change to `_needs-notebooklm`
5. **Add to NotebookLM**: Upload PDFs to NotebookLM
6. **Save insights**: Store summaries and analysis
7. **Mark complete**: Change status to `_complete`
8. **Build argument map**: Extract propositions from insights, organize into topics
9. **Search your map**: Use GraphRAG search to find relevant subgraphs for your writing
10. **Identify gaps**: Find salient propositions lacking grounded evidence
11. **Synthesize**: Query your knowledge base for cross-paper insights

## API Keys (Optional)

All search tools work without API keys but have rate limits:

| Service | Without Key | With Key | Get Key |
|---------|------------|----------|---------|
| PubMed | 3 req/sec | 10 req/sec | https://www.ncbi.nlm.nih.gov/account/ |
| Semantic Scholar | 100 req/5min | 5000 req/5min | https://www.semanticscholar.org/product/api |
| ERIC | Unlimited | N/A | No key needed |

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=litrev_mcp

# Run only unit tests (skip integration)
SKIP_INTEGRATION_TESTS=1 pytest

# Run specific test file
pytest tests/test_zotero.py -v
```

## Setting Up on Additional Machines

Already have litrev-mcp on one machine? Here's how to set up on another:

**1. Install prerequisites** (Python, Zotero, Better BibTeX, Google Drive)

**2. Wait for Google Drive sync**
   - Ensure `Literature/` folder and contents are synced
   - Check `Literature/.litrev/config.yaml` exists

**3. Install litrev-mcp**
   ```bash
   uv tool install litrev-mcp
   ```

**4. Set environment variables** (per-machine, not synced)
   ```bash
   export ZOTERO_API_KEY="your-key"
   export ZOTERO_USER_ID="your-id"
   export OPENAI_API_KEY="your-key"  # if using RAG
   export MOTHERDUCK_TOKEN="your-token"
   source ~/.bashrc  # or ~/.zshrc
   ```

**5. Add MCP server** (if not already done in another repo on this machine)
   ```bash
   claude mcp add litrev -- litrev-mcp
   ```
   **Note:** MCP servers are per-project. If you've already done this on another repository on this machine, you don't need to repeat it—the same server instance is shared.

**6. Verify**
   ```
   > Use setup_check
   ```

That's it! Your config, PDFs, notes, and database are already synced — no need to reindex.

## Database Management

### MotherDuck Cloud Database

**Location:** MotherDuck cloud (default database name: `litrev`). Configure via `config.yaml`:
```yaml
database:
  motherduck_database: litrev  # default
```

Stores both RAG search indexes (paper chunks + embeddings) and the argument map (propositions, relationships, evidence, topics, issues, proposition embeddings).

**Cloud syncing:** The database is hosted on MotherDuck and automatically accessible from all machines — no need to rebuild indexes when switching computers.

**Size:** Approximately:
- 50 papers: ~10-20 MB
- 200 papers: ~50-100 MB
- 1000 papers: ~300-500 MB

**Backup:** MotherDuck handles persistence. Data can also be regenerated with `index_papers`.

**Optimization:** For large collections (500+ papers), set:
```yaml
rag:
  embedding_dimensions: 512  # Instead of default 1536
```
Reduces storage by ~66% with minimal quality impact.

**Migration from local DuckDB:** If you have an existing local `literature.duckdb` file, use the migration script:
```bash
python scripts/migrate_to_motherduck.py path/to/Literature/.litrev/literature.duckdb
```

## Upgrading

**Update to latest version:**
```bash
uv tool upgrade litrev-mcp
```

**Verify:**
```bash
litrev-mcp --version
```

**After upgrading:**
1. Check if config format changed: `> Use setup_check`
2. If config issues, compare with default in spec.md
3. May need to reindex if embedding dimensions changed

**Downgrade** (if needed):
```bash
uv tool uninstall litrev-mcp
uv tool install litrev-mcp==0.2.1  # specify version
```

## Troubleshooting

### "citation key not found"

**Cause:** Better BibTeX not installed
**Fix:** Install Better BibTeX plugin in Zotero (see [Prerequisites](#better-bibtex-setup))

### "OPENAI_API_KEY not set" when using ask_papers

**Cause:** OpenAI key required for RAG features
**Fix:** Set `export OPENAI_API_KEY="your-key"` and reload shell

### "Failed to connect to litrev MCP server"

**Cause:** Python environment mismatch or server crashed
**Fix:** Remove and re-add with full path:
```bash
claude mcp remove litrev
claude mcp add litrev -- /full/path/to/.venv/Scripts/python.exe -m litrev_mcp.server
```
Or check server health: `python -m litrev_mcp.server`

### Windows: "Cannot find Google Drive"

**Cause:** Drive letter varies by machine
**Fix:** Set explicitly:
```bash
export LITREV_DRIVE_PATH="C:/Users/YourName/Google Drive"
```

### Database too large

**Cause:** Using default 1536 dimensions with 500+ papers
**Fix:** Edit `Literature/.litrev/config.yaml`:
```yaml
rag:
  embedding_dimensions: 512
```
Then delete `literature.duckdb` and reindex.

### "Google Drive path not detected"

Set the `LITREV_DRIVE_PATH` environment variable:
```bash
export LITREV_DRIVE_PATH="/path/to/Google Drive"
```

### "ZOTERO_API_KEY not set"

Add to your shell configuration and reload:
```bash
export ZOTERO_API_KEY="your-key"
export ZOTERO_USER_ID="your-id"
source ~/.bashrc
```

### "Project not found"

Create the project:
```
> Create a new project with code "PROJECT" and name "My Project"
```

Or add manually to `Literature/.litrev/config.yaml`.

### MCP Server Not Responding

1. Check Claude Code logs
2. Verify installation: `which litrev-mcp`
3. Test server: `python -m litrev_mcp.server`
4. Restart Claude Code

## Development

### Project Structure

```
litrev-mcp/
├── src/litrev_mcp/
│   ├── server.py               # MCP server entry point (61 tools)
│   ├── config.py               # Configuration management
│   └── tools/
│       ├── zotero.py           # Zotero operations
│       ├── pubmed.py           # PubMed search
│       ├── semantic_scholar.py # Semantic Scholar
│       ├── eric.py             # ERIC search
│       ├── insights.py         # Knowledge base
│       ├── status.py           # Dashboard tools
│       ├── setup.py            # Setup wizard
│       ├── pdf.py              # PDF processing
│       ├── rag.py              # RAG search tools
│       ├── rag_db.py           # DuckDB RAG operations
│       ├── rag_embed.py        # Embeddings & chunking
│       ├── concept_map_db.py   # Argument map DB (propositions, topics, issues)
│       └── argument_map_search.py  # GraphRAG search & traversal
├── tests/
│   ├── test_zotero.py
│   ├── test_search_apis.py
│   ├── test_insights.py
│   ├── test_status.py
│   ├── test_setup.py
│   ├── test_rag.py
│   └── test_argument_map_search.py
├── docs/                       # Reference guide (HTML)
├── pyproject.toml
└── README.md
```

### Running Tests

```bash
# All tests
pytest

# Specific module
pytest tests/test_zotero.py

# With verbose output
pytest -v

# With integration tests
pytest  # Integration tests run if credentials available

# Skip integration tests
SKIP_INTEGRATION_TESTS=1 pytest
```

### Code Quality

```bash
# Format code
black src tests

# Lint
ruff check src tests

# Type check
mypy src
```

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- Built on the [Model Context Protocol](https://modelcontextprotocol.io/)
- Integrates with [Zotero](https://www.zotero.org/) and [Better BibTeX](https://retorque.re/zotero-better-bibtex/)
- Uses [PubMed](https://pubmed.ncbi.nlm.nih.gov/), [Semantic Scholar](https://www.semanticscholar.org/), and [ERIC](https://eric.ed.gov/) APIs
