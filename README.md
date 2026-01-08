# litrev-mcp

MCP server for AI-assisted literature review with Zotero, PubMed, and Semantic Scholar integration.

## Overview

An MCP (Model Context Protocol) server that provides literature review tools to Claude. Enables systematic literature discovery, retrieval, and organization with Zotero as the central repository. Supports PubMed, Semantic Scholar, and ERIC searches, citation snowballing, and a local knowledge base for storing and querying AI-generated insights from Consensus and NotebookLM.

## Status

✅ **v0.2.2 - Intelligent Literature Synthesis**

- 29 tools across 8 categories
- Full Zotero integration
- Search APIs (PubMed, Semantic Scholar, ERIC)
- Knowledge base system
- Semantic search over your PDFs (DuckDB + OpenAI embeddings)
- Project context for tailored responses (goal, audience, style)
- **NEW: Claude-powered synthesis with coverage assessment** - `ask_papers` now provides reasoned answers that honestly assess literature coverage and suggest follow-up searches when gaps exist
- Project dashboard
- Setup wizard

## Features

### Zotero Integration (9 tools)
- `zotero_list_projects` - List collections with paper counts by status
- `zotero_create_collection` - Create a new Zotero collection
- `zotero_add_paper` - Add papers by DOI or manual entry
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

### RAG Literature Search (4 tools)
- `index_papers` - Index PDFs for semantic search (extracts text, chunks, generates OpenAI embeddings)
- `search_papers` - Semantic search across indexed papers, returns passages with citations
- `ask_papers` - Ask questions about your literature; uses Claude to synthesize a reasoned answer with honest assessment of coverage adequacy and recommendations for follow-up searches when gaps exist
- `rag_status` - View indexing status and statistics

### Status & Dashboard (2 tools)
- `project_status` - Get comprehensive project dashboard
- `pending_actions` - Get all pending user actions (PDFs to acquire, papers for NotebookLM)

### Setup Wizard (2 tools)
- `setup_check` - Verify configuration (Google Drive, Zotero credentials)
- `setup_create_project` - Create new project with directory structure

### Project Context (2 tools)
- `get_project_context` - Get project context (goal, audience, style) from _context.md
- `update_project_context` - Create or update project context file

Use `/init-litrev-context PROJECT` skill for collaborative context setup.

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
- `Literature/.litrev/literature.duckdb` - RAG search database

**What syncs across machines:**
| Item | Syncs? | Location |
|------|--------|----------|
| Config file | ✅ Yes | `Literature/.litrev/config.yaml` |
| PDFs | ✅ Yes | `Literature/{PROJECT}/` |
| Notes | ✅ Yes | `Literature/{PROJECT}/_notes/` |
| DuckDB index | ❌ No (per-machine) | `Literature/.litrev/literature.duckdb` |
| Environment vars | ❌ No (per-machine) | `~/.bashrc` or `~/.zshrc` |

**Important:** After setting up on a new machine, you'll need to run `index_papers` again to rebuild the RAG index.

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

### 1. Get Zotero Credentials

Visit https://www.zotero.org/settings/keys and create a new private key with:
- ✓ Allow library access
- ✓ Allow notes access
- ✓ Allow write access

Copy both your **API Key** and **User ID**.

### 2. Set Environment Variables

Add to your shell configuration (`~/.bashrc`, `~/.zshrc`, or `~/.bash_profile`):

```bash
# Required for all features
export ZOTERO_API_KEY="your-api-key-here"         # From https://www.zotero.org/settings/keys
export ZOTERO_USER_ID="your-user-id-here"        # Numeric ID from same page

# Required for RAG features (index_papers, search_papers, ask_papers)
export OPENAI_API_KEY="your-openai-key"  # Get from https://platform.openai.com/api-keys

# Optional - improves rate limits
export NCBI_API_KEY="your-ncbi-key"           # Get from https://www.ncbi.nlm.nih.gov/account/
export SEMANTIC_SCHOLAR_API_KEY="your-s2-key"  # Get from https://www.semanticscholar.org/product/api

# Optional - override Google Drive detection (Windows users especially)
export LITREV_DRIVE_PATH="/path/to/your/Google Drive"
```

**Reload your shell configuration:**

<details>
<summary><b>bash</b> (most Linux, older macOS)</summary>

```bash
source ~/.bashrc
# OR restart your terminal
```
</details>

<details>
<summary><b>zsh</b> (newer macOS, some Linux)</summary>

```bash
source ~/.zshrc
# OR restart your terminal
```
</details>

<details>
<summary><b>Windows Git Bash / MSYS</b></summary>

```bash
source ~/.bashrc
# OR restart your terminal
```
</details>

**Verify:** Open a NEW terminal and run `echo $ZOTERO_API_KEY` - it should show your key.

### 3. Configure Claude Code

Add the MCP server to Claude Code:

```bash
claude mcp add litrev -- litrev-mcp
```

**Important:** You need to run this command **in every repository** where you want to use litrev-mcp. MCP servers are registered per-project. After the first setup, just navigate to each new project directory and run the same command.

### 4. Verify Setup

In Claude Code:
```
> Use setup_check to verify my configuration
```

### 5. Install Skill (Optional)

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
    │   ├── config.yaml          # Project configuration
    │   └── literature.duckdb    # RAG vector index (auto-created)
    ├── MEAS-ERR/                # Project directory
    │   ├── _context.md          # Project context (goal, audience, style)
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
8. **Synthesize**: Query your knowledge base for cross-paper insights

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

**7. Reindex papers** (DuckDB doesn't sync)
   ```
   > Use index_papers for project "PROJECT-CODE"
   ```

That's it! Your config, PDFs, and notes are already synced from the first machine.

## Database Management

### DuckDB RAG Index

**Location:** `Literature/.litrev/literature.duckdb`

**Size:** Approximately:
- 50 papers: ~10-20 MB
- 200 papers: ~50-100 MB
- 1000 papers: ~300-500 MB

**Backup:** Not necessary - can be regenerated with `index_papers`

**Syncing:** Database does NOT sync via Google Drive (too large, causes conflicts)
- Each machine maintains its own index
- After setting up a new machine, run `index_papers` to rebuild

**Corruption:** If you suspect corruption:
1. Delete `literature.duckdb`
2. Run `index_papers` again

**Optimization:** For large collections (500+ papers), set:
```yaml
rag:
  embedding_dimensions: 512  # Instead of default 1536
```
Reduces storage by ~66% with minimal quality impact.

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
│   ├── server.py           # MCP server entry point
│   ├── config.py           # Configuration management
│   └── tools/
│       ├── zotero.py       # Zotero operations
│       ├── pubmed.py       # PubMed search
│       ├── semantic_scholar.py  # Semantic Scholar
│       ├── eric.py         # ERIC search
│       ├── insights.py     # Knowledge base
│       ├── status.py       # Dashboard tools
│       ├── setup.py        # Setup wizard
│       ├── pdf.py          # PDF processing
│       ├── rag.py          # RAG search tools
│       ├── rag_db.py       # DuckDB operations
│       └── rag_embed.py    # Embeddings & chunking
├── tests/
│   ├── test_zotero.py
│   ├── test_search_apis.py
│   ├── test_insights.py
│   ├── test_status.py
│   ├── test_setup.py
│   └── test_rag.py
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
