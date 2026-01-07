# litrev-mcp

MCP server for AI-assisted literature review with Zotero, PubMed, and Semantic Scholar integration.

## Overview

An MCP (Model Context Protocol) server that provides literature review tools to Claude. Enables systematic literature discovery, retrieval, and organization with Zotero as the central repository. Supports PubMed, Semantic Scholar, and ERIC searches, citation snowballing, and a local knowledge base for storing and querying AI-generated insights from Consensus and NotebookLM.

## Status

✅ **v0.1.0 - All Core Features Implemented**

- 22 tools across 6 categories
- 67+ unit tests
- Full Zotero integration
- Search APIs (PubMed, Semantic Scholar, ERIC)
- Knowledge base system
- Project dashboard
- Setup wizard

## Features

### Zotero Integration (8 tools)
- `zotero_list_projects` - List collections with paper counts by status
- `zotero_create_collection` - Create a new Zotero collection
- `zotero_add_paper` - Add papers by DOI or manual entry
- `zotero_update_status` - Change status tags (_needs-pdf, _needs-notebooklm, _complete)
- `zotero_get_by_status` - Filter papers by status
- `zotero_search` - Search your library
- `zotero_get_citation_key` - Get Better BibTeX citation keys
- `process_pdf_inbox` - Process PDFs in to_add folder, match to Zotero entries, rename and organize

### Literature Search (5 tools)
- `pubmed_search` - Search PubMed for biomedical papers
- `semantic_scholar_search` - Search Semantic Scholar across all fields
- `semantic_scholar_references` - Backward snowball (papers cited BY a paper)
- `semantic_scholar_citations` - Forward snowball (papers that CITE a paper)
- `eric_search` - Search ERIC for education research

### Knowledge Base (4 tools)
- `save_insight` - Save Consensus/NotebookLM summaries and notes
- `search_insights` - Search saved insights by keyword
- `analyze_insights` - Answer questions from saved insights
- `list_insights` - List all insights for a project

### Status & Dashboard (2 tools)
- `project_status` - Get comprehensive project dashboard
- `pending_actions` - Get all pending user actions (PDFs to acquire, papers for NotebookLM)

### Setup Wizard (2 tools)
- `setup_check` - Verify configuration (Google Drive, Zotero credentials)
- `setup_create_project` - Create new project with directory structure

### Test Tool (1 tool)
- `litrev_hello` - Verify litrev-mcp is working

## Prerequisites

- Python 3.10+
- [Zotero](https://www.zotero.org/) with [Better BibTeX](https://retorque.re/zotero-better-bibtex/) plugin
- Google Drive (for PDF storage and config sync)
- Claude Code or Claude Desktop with MCP support

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
# Required
export ZOTERO_API_KEY="your-api-key-here"
export ZOTERO_USER_ID="your-user-id-here"

# Optional (improves rate limits)
export NCBI_API_KEY="your-ncbi-key"  # Get from https://www.ncbi.nlm.nih.gov/account/
export SEMANTIC_SCHOLAR_API_KEY="your-s2-key"  # Get from https://www.semanticscholar.org/product/api

# Optional (override Google Drive detection)
export LITREV_DRIVE_PATH="/path/to/your/Google Drive"
```

Reload your shell: `source ~/.bashrc`

### 3. Configure Claude Code

Add the MCP server to Claude Code:

```bash
claude mcp add litrev -- litrev-mcp
```

### 4. Verify Setup

In Claude Code:
```
> Use setup_check to verify my configuration
```

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
```

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

## Troubleshooting

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
│       └── setup.py        # Setup wizard
├── tests/
│   ├── test_zotero.py
│   ├── test_search_apis.py
│   ├── test_insights.py
│   ├── test_status.py
│   └── test_setup.py
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
