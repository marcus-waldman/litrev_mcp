# Literature Review MCP Server — Implementation Specification

## Overview

Build an MCP (Model Context Protocol) server that provides literature review tools to Claude Code. The server enables systematic literature discovery, retrieval, and organization across multiple research projects.

The key design principle is **agent as orchestrator**: the agent executes API-based operations directly, but delegates browser-based tasks (Consensus, NotebookLM, Google Scholar) back to the user with clear instructions.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLAUDE CODE                            │
│              (Uses MCP tools from any directory)            │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    LITREV MCP SERVER                        │
├─────────────────────────────────────────────────────────────┤
│  Tools:                                                     │
│    • Zotero (pyzotero)                                      │
│    • PubMed (biopython Bio.Entrez)                          │
│    • Semantic Scholar (semanticscholar)                     │
│    • ERIC (custom REST wrapper)                             │
│    • Project status & orchestration                         │
│    • Setup wizard                                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        ZOTERO                               │
│                   (Central repository)                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
litrev-mcp/
├── src/
│   └── litrev_mcp/
│       ├── __init__.py
│       ├── server.py              # MCP server entry point
│       ├── config.py              # Configuration management
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── zotero.py          # Zotero operations
│       │   ├── pubmed.py          # PubMed search
│       │   ├── semantic_scholar.py # Semantic Scholar search + snowball
│       │   ├── eric.py            # ERIC search (thin REST wrapper)
│       │   ├── status.py          # Project status queries
│       │   └── insights.py        # Insight storage & retrieval
│       └── setup/
│           ├── __init__.py
│           └── wizard.py          # Setup subagent logic
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## Dependencies

```toml
[project]
name = "litrev-mcp"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "mcp",
    "pyzotero",
    "biopython",
    "semanticscholar",
    "httpx",           # For ERIC REST calls
    "pydantic",        # For configuration validation
    "pyyaml",          # For config file
]

[project.scripts]
litrev-mcp = "litrev_mcp.server:main"
```

### Zotero Requirements

- **Better BibTeX plugin** must be installed in Zotero
- BBT automatically generates citation keys and exposes them via Zotero's Extra field or the BBT JSON API
- The citation key pattern in config should match your BBT settings

**Implementation note:** Better BibTeX stores the citation key in the item's `extra` field (as `Citation Key: xxx`) or can be accessed via BBT's own API. When fetching items via pyzotero, parse the `extra` field to extract the citation key. Example:

```python
def get_citation_key(item):
    extra = item.get('data', {}).get('extra', '')
    for line in extra.split('\n'):
        if line.startswith('Citation Key:'):
            return line.split(':', 1)[1].strip()
    return None
```

---

## Configuration

### Storage Model

| What | Where | Why |
|------|-------|-----|
| API keys | Local env vars | Secrets shouldn't sync |
| MCP config | Local Claude config | Per-installation |
| Project definitions | Google Drive (.litrev/) | Syncs across machines |
| Paper metadata | Zotero | Already syncs |
| PDFs (primary) | Zotero attachments | Reading, annotation, standard workflow |
| PDFs (copy) | Google Drive | NotebookLM access |

### Environment Variables (per-machine secrets)

```bash
ZOTERO_API_KEY=xxxxx       # Required
ZOTERO_USER_ID=xxxxx       # Required  
NCBI_API_KEY=xxxxx         # Optional, increases PubMed rate limit
SEMANTIC_SCHOLAR_API_KEY=xxxxx  # Optional, increases rate limit
LITREV_DRIVE_PATH=xxxxx    # Path to Literature folder (if not ~/Google Drive/Literature)
```

### Config File (Google Drive — syncs across machines)

Location: `Literature/.litrev/config.yaml`

The agent should auto-detect the Google Drive path:
- macOS: `~/Library/CloudStorage/GoogleDrive-{email}/My Drive/Literature/`
- Linux: `~/google-drive/Literature/` (varies by client)
- Windows: `G:\My Drive\Literature\` (varies)

Or use `LITREV_DRIVE_PATH` env var if set.

```yaml
# Literature/.litrev/config.yaml
# This file syncs across all your machines via Google Drive

# Project definitions
projects:
  MEAS-ERR:
    name: "Measurement Error in Biomedical Science"
    zotero_collection_key: "ABC123"  # Looked up once, cached here
    notebooklm_notebooks:
      - "MEAS-ERR - Paper - Glucose OGTT methods"
    
  MOD-SEL:
    name: "Model Selection with Missing Data"
    zotero_collection_key: "DEF456"
    notebooklm_notebooks: []

# Status tags used in Zotero
status_tags:
  needs_pdf: "_needs-pdf"
  needs_notebooklm: "_needs-notebooklm"
  complete: "_complete"

# NotebookLM naming convention (for user instructions)
notebooklm_pattern: "{project_code} - {type} - {descriptor}"

# Better BibTeX configuration
better_bibtex:
  citation_key_pattern: "[auth:lower]_[shorttitle3_3:lower]_[year]"
```

### Folder Structure (Google Drive)

```
Literature/                          # Root folder in Google Drive
├── .litrev/
│   └── config.yaml                  # Synced configuration
├── MEAS-ERR/
│   ├── _notes/                      # Saved insights & synthesis
│   │   ├── 2024-01-15_consensus_glucose_methods.md
│   │   ├── 2024-01-18_notebooklm_simex_comparison.md
│   │   └── 2024-01-20_synthesis_chapter2_draft.md
│   ├── carroll_measurement_2006.pdf
│   ├── buonaccorsi_measurement_2010.pdf
│   └── fuller_measurement_1987.pdf
├── MOD-SEL/
│   ├── _notes/
│   │   └── ...
│   └── ...
└── GSED/
    └── ...
```

**What goes in `_notes/`:**
- Consensus search summaries (with the query that produced them)
- NotebookLM Q&A transcripts  
- Your own synthesis notes
- Reading notes and annotations
- Draft sections and outlines

**Naming convention:** `{date}_{source}_{topic}.md`

---

## Better BibTeX Integration

### Why This Matters

The citation key serves as the **universal identifier** across all systems:

| System | Uses Citation Key As |
|--------|---------------------|
| Zotero + BBT | Citation key field |
| Google Drive | PDF filename (`{key}.pdf`) |
| NotebookLM | Source name (derived from filename) |
| Quarto/LaTeX | `@key` citation |

This alignment means NotebookLM citations can be directly used in your manuscripts.

### PDF Storage Model

PDFs live in **two places**:

| Location | Purpose | Syncs via |
|----------|---------|-----------|
| Zotero (attached to item) | Primary storage, reading, annotation | Zotero cloud |
| Google Drive | NotebookLM access | Google Drive |

This duplication is intentional — NotebookLM can't read from Zotero, and Zotero is the natural home for academic PDFs.

### PDF Naming Convention

**Critical:** When saving PDFs to Google Drive, always use the citation key as the filename:

```
Literature/
├── MEAS-ERR/
│   ├── carroll_measurement_2006.pdf
│   ├── buonaccorsi_measurement_2010.pdf
│   └── fuller_measurement_1987.pdf
├── MOD-SEL/
│   └── ...
```

When you add these to NotebookLM, it will cite them using the filename (minus extension), which matches your Quarto citation keys exactly.

**Note:** Zotero doesn't enforce filenames for attachments — the citation key alignment is specifically for the Drive copy so NotebookLM citations match your Quarto references.

### Workflow with Citation Keys

```
Paper added to Zotero
         │
         ▼
BBT generates key: carroll_measurement_2006
         │
         ▼
Agent returns: "Added. Citation key: carroll_measurement_2006
               Save PDF as: carroll_measurement_2006.pdf"
         │
         ▼
User acquires PDF → renames to carroll_measurement_2006.pdf
         │
         ▼
User uploads to: Literature/MEAS-ERR/carroll_measurement_2006.pdf
         │
         ▼
User adds to NotebookLM (source name auto-detected from filename)
         │
         ▼
NotebookLM cites as: carroll_measurement_2006 ✓
         │
         ▼
In Quarto: @carroll_measurement_2006 ✓ (same key!)
```

---

## Tool Specifications

### Zotero Tools

#### `zotero_list_projects`

List all collections (projects) with paper counts by status.

**Parameters:** None

**Returns:**
```json
{
  "projects": [
    {
      "key": "ABC123",
      "name": "Measurement Error in Biomedical Science",
      "code": "MEAS-ERR",
      "total_papers": 42,
      "needs_pdf": 5,
      "needs_notebooklm": 3,
      "complete": 34
    }
  ]
}
```

---

#### `zotero_add_paper`

Add a paper to Zotero by DOI or manual metadata. Automatically tags with `_needs-pdf`. Returns citation key for PDF naming.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | yes | Project code (e.g., "MEAS-ERR") |
| doi | string | no | DOI — if provided, fetches metadata automatically |
| title | string | no | Manual title (if no DOI) |
| authors | string | no | Manual authors (if no DOI) |
| year | integer | no | Manual year (if no DOI) |
| source | string | no | Where this was found (e.g., "PubMed", "Consensus") |

**Returns:**
```json
{
  "success": true,
  "item_key": "XYZ789",
  "citation_key": "carroll_measurement_2006",
  "title": "Measurement Error in Nonlinear Models",
  "drive_filename": "carroll_measurement_2006.pdf",
  "drive_folder": "Literature/MEAS-ERR/",
  "message": "Added to MEAS-ERR. Tagged as _needs-pdf."
}
```

**Agent behavior:** After adding, instruct user to:
1. Attach PDF to this Zotero item
2. Save copy to Drive as `{drive_filename}` in `{drive_folder}`

---

#### `zotero_update_status`

Update the status tag on a paper.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| item_key | string | yes* | Zotero item key |
| doi | string | yes* | Or identify by DOI |
| title_search | string | yes* | Or search by title fragment |
| new_status | string | yes | One of: "needs_pdf", "needs_notebooklm", "complete" |

*One of item_key, doi, or title_search required.

**Returns:**
```json
{
  "success": true,
  "item_key": "XYZ789",
  "title": "Measurement Error in Nonlinear Models",
  "old_status": "needs_pdf",
  "new_status": "needs_notebooklm"
}
```

---

#### `zotero_get_by_status`

Get papers filtered by status within a project.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | yes | Project code |
| status | string | yes | One of: "needs_pdf", "needs_notebooklm", "complete", "all" |

**Returns:**
```json
{
  "project": "MEAS-ERR",
  "status": "needs_pdf",
  "count": 5,
  "papers": [
    {
      "item_key": "XYZ789",
      "citation_key": "carroll_measurement_2006",
      "title": "Measurement Error in Nonlinear Models",
      "authors": "Carroll, Ruppert, Stefanski",
      "year": 2006,
      "doi": "10.1201/9781420010138",
      "pdf_filename": "carroll_measurement_2006.pdf"
    }
  ]
}
```

---

#### `zotero_search`

Search within your Zotero library.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | Search query |
| project | string | no | Limit to specific project |

**Returns:** Same format as `zotero_get_by_status`, with `citation_key` included for each paper.

---

#### `zotero_get_citation_key`

Get Better BibTeX citation key(s) for paper(s). Useful when writing and you need the cite key.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| item_key | string | no* | Zotero item key |
| doi | string | no* | Identify by DOI |
| title_search | string | no* | Search by title fragment (may return multiple) |

*At least one required.

**Returns:**
```json
{
  "results": [
    {
      "item_key": "XYZ789",
      "citation_key": "carroll_measurement_2006",
      "title": "Measurement Error in Nonlinear Models: A Modern Perspective",
      "authors": "Carroll, Ruppert, Stefanski, Crainiceanu",
      "year": 2006,
      "bibtex": "@book{carroll_measurement_2006,\n  author = {Carroll, Raymond J. and ...},\n  title = {Measurement Error in Nonlinear Models},\n  year = {2006},\n  ...\n}",
      "pdf_filename": "carroll_measurement_2006.pdf"
    }
  ]
}
```

**Note:** The `pdf_filename` field is the recommended filename for Google Drive/NotebookLM alignment.

---

### Search Tools

#### `pubmed_search`

Search PubMed for papers.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | Search query (supports PubMed syntax) |
| max_results | integer | no | Default 10, max 50 |

**Returns:**
```json
{
  "source": "PubMed",
  "query": "measurement error glucose",
  "count": 10,
  "results": [
    {
      "pmid": "12345678",
      "title": "...",
      "authors": "...",
      "year": 2020,
      "journal": "...",
      "doi": "...",
      "abstract": "..."
    }
  ]
}
```

---

#### `eric_search`

Search ERIC for education research.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | Search query |
| max_results | integer | no | Default 10, max 50 |

**Returns:** Same structure as pubmed_search, with `eric_id` instead of `pmid`.

**Implementation notes:**
- ERIC API endpoint: `https://api.ies.ed.gov/eric/`
- No authentication required
- Simple REST GET with query parameters
- Parse JSON response

---

#### `semantic_scholar_search`

Search Semantic Scholar.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | Search query |
| max_results | integer | no | Default 10, max 100 |

**Returns:** Same structure, with `s2_id` (Semantic Scholar paper ID) and `citation_count`.

---

#### `semantic_scholar_references`

Backward snowball: get papers cited BY a given paper.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| paper_id | string | yes | DOI, S2 ID, or PMID |
| max_results | integer | no | Default 50 |

**Returns:**
```json
{
  "source_paper": {
    "title": "...",
    "doi": "..."
  },
  "reference_count": 42,
  "references": [
    {
      "s2_id": "...",
      "title": "...",
      "authors": "...",
      "year": 2005,
      "doi": "...",
      "citation_count": 1500,
      "is_influential": true
    }
  ]
}
```

---

#### `semantic_scholar_citations`

Forward snowball: get papers that CITE a given paper.

**Parameters:** Same as `semantic_scholar_references`

**Returns:** Same structure, with `citations` instead of `references`.

---

### Status Tools

#### `project_status`

Get a dashboard view of a project.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | yes | Project code |

**Returns:**
```json
{
  "project": "MEAS-ERR",
  "name": "Measurement Error in Biomedical Science",
  "summary": {
    "total": 42,
    "needs_pdf": 5,
    "needs_notebooklm": 3,
    "complete": 34
  },
  "insights": {
    "total": 12,
    "by_source": {
      "consensus": 4,
      "notebooklm": 5,
      "synthesis": 2,
      "reading_notes": 1
    }
  },
  "recent_additions": [
    {"title": "...", "added": "2024-01-15", "status": "needs_pdf"}
  ],
  "recent_insights": [
    {"topic": "glucose_methods", "source": "consensus", "date": "2024-01-15"}
  ],
  "drive_folder": "Literature/MEAS-ERR",
  "notebooklm_notebooks": ["MEAS-ERR - Paper - Glucose OGTT methods"]
}
```

---

#### `pending_actions`

Get all pending user actions across projects. Includes all information needed to provide complete acquisition instructions for both Zotero and Google Drive.

**Parameters:** None

**Returns:**
```json
{
  "pdfs_to_acquire": [
    {
      "project": "MEAS-ERR",
      "citation_key": "smith_glucose_2019",
      "title": "Glucose measurement methods...",
      "authors": "Smith, Jones, Williams",
      "year": 2019,
      "doi": "10.xxx/xxx",
      "doi_url": "https://doi.org/10.xxx/xxx",
      "item_key": "ABC123",
      "zotero_item_title": "Glucose measurement methods...",
      "drive_filename": "smith_glucose_2019.pdf",
      "drive_folder": "Literature/MEAS-ERR/"
    }
  ],
  "papers_to_add_to_notebooklm": [
    {
      "project": "MEAS-ERR",
      "citation_key": "carroll_measurement_2006",
      "title": "Measurement Error in Nonlinear Models",
      "drive_filename": "carroll_measurement_2006.pdf",
      "drive_folder": "Literature/MEAS-ERR/",
      "drive_full_path": "Literature/MEAS-ERR/carroll_measurement_2006.pdf",
      "suggested_notebook": "MEAS-ERR - Paper - Glucose OGTT methods"
    }
  ]
}
```

**Agent behavior:** When presenting `pdfs_to_acquire`, always instruct user to:
1. Attach PDF to Zotero item (primary storage)
2. Save copy to Google Drive with citation key filename (for NotebookLM)
```

---

### Insights Tools

The insights system stores AI-generated summaries, synthesis notes, and reading notes as a searchable knowledge base. This enables the agent to answer questions from accumulated knowledge, detect contradictions, and identify gaps.

#### `save_insight`

Save a Consensus summary, NotebookLM answer, or synthesis note.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | yes | Project code |
| source | string | yes | "consensus", "notebooklm", "synthesis", "reading_notes" |
| topic | string | yes | Brief descriptor (becomes part of filename) |
| content | string | yes | The actual content to save |
| query | string | no | Original question that prompted this (for Consensus/NLM) |
| papers_referenced | list | no | Citation keys of papers mentioned |

**Returns:**
```json
{
  "success": true,
  "filepath": "Literature/MEAS-ERR/_notes/2024-01-15_consensus_glucose_methods.md",
  "message": "Saved insight to MEAS-ERR notes"
}
```

**File format:** Markdown with YAML frontmatter:
```markdown
---
date: 2024-01-15
source: consensus
topic: glucose_methods
query: "glucose measurement error correction methods in longitudinal studies"
papers_referenced:
  - carroll_measurement_2006
  - fuller_measurement_1987
---

[Content of the insight...]
```

**Storage location:** `Literature/{PROJECT}/_notes/{date}_{source}_{topic}.md`

---

#### `search_insights`

Search saved insights and return content for synthesis.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| query | string | yes | Search query or question |
| project | string | no | Limit to specific project |
| source | string | no | Filter: "consensus", "notebooklm", "synthesis", "reading_notes", "all" |
| max_results | int | no | Default 10 |

**Returns:**
```json
{
  "query": "SIMEX vs regression calibration",
  "total_matches": 3,
  "matches": [
    {
      "filepath": "Literature/MEAS-ERR/_notes/2024-01-15_consensus_glucose_methods.md",
      "source": "consensus",
      "date": "2024-01-15",
      "topic": "glucose_methods",
      "original_query": "glucose measurement error correction methods",
      "content": "Full text of the note...",
      "papers_referenced": ["carroll_measurement_2006", "fuller_measurement_1987"],
      "relevance_snippet": "...SIMEX is preferred when the measurement error distribution is known..."
    }
  ]
}
```

**Agent behavior:** After retrieving insights, synthesize across them, attribute claims to sources, and flag any tensions.

---

#### `analyze_insights`

Analyze insights to answer a question, compare sources, or detect tensions/contradictions.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| question | string | yes | The question to answer or analyze |
| project | string | no | Limit to specific project |
| mode | string | no | "answer" (default), "compare", "tensions" |

**Returns:**
```json
{
  "question": "When should I use SIMEX vs regression calibration?",
  "mode": "answer",
  "insights_analyzed": 3,
  "sources_used": [
    {
      "filepath": "2024-01-15_consensus_glucose_methods.md",
      "source": "consensus",
      "date": "2024-01-15"
    }
  ],
  "synthesis": "Based on your saved insights...",
  "tensions_detected": [
    {
      "topic": "Sample size requirements for SIMEX",
      "claims": [
        {
          "file": "2024-01-15_consensus_glucose_methods.md",
          "claim": "SIMEX requires n > 500 for stable estimates"
        },
        {
          "file": "2024-01-18_nlm_correction_comparison.md",
          "claim": "Carroll (2006) suggests n > 200 is sufficient"
        }
      ],
      "suggested_resolution": "Check Carroll (2006) Chapter 5 directly"
    }
  ],
  "gaps_identified": [
    "No insights found about SIMEX with non-normal error distributions"
  ]
}
```

**Mode behaviors:**
- `answer`: Synthesize insights to answer the question directly
- `compare`: Show how different sources address the same topic
- `tensions`: Focus on finding contradictions and conflicts

---

#### `list_insights`

List all saved insights for a project.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| project | string | yes | Project code |
| source | string | no | Filter by source type |

**Returns:**
```json
{
  "project": "MEAS-ERR",
  "total_insights": 12,
  "insights": [
    {
      "filepath": "Literature/MEAS-ERR/_notes/2024-01-15_consensus_glucose_methods.md",
      "source": "consensus",
      "date": "2024-01-15",
      "topic": "glucose_methods",
      "papers_referenced": ["carroll_measurement_2006"]
    }
  ],
  "by_source": {
    "consensus": 4,
    "notebooklm": 5,
    "synthesis": 2,
    "reading_notes": 1
  }
}
```

---

### Setup Tools

#### `setup_check`

Check what's configured and what's missing. Creates a Claude todo list for incomplete items.

**Parameters:** None

**Returns:**
```json
{
  "status": "incomplete",
  "checks": {
    "python": {"ok": true, "version": "3.11.5"},
    "uv_or_pip": {"ok": true, "tool": "uv"},
    "litrev_mcp_installed": {"ok": false},
    "zotero_api_key": {"ok": false},
    "zotero_user_id": {"ok": false},
    "zotero_connection": {"ok": false},
    "better_bibtex": {"ok": false, "message": "Cannot verify until Zotero connected"},
    "ncbi_api_key": {"ok": false, "required": false},
    "config_file": {"ok": false},
    "projects_defined": {"ok": false}
  },
  "todo_list": [
    "Install Python 3.10+",
    "Install litrev-mcp package",
    "Create Zotero API key",
    "Set ZOTERO_API_KEY environment variable",
    "Set ZOTERO_USER_ID environment variable",
    "Install Better BibTeX in Zotero",
    "Create config file",
    "Create first project"
  ]
}
```

**Agent behavior:** When setup is incomplete, create a Claude todo list and walk through items one by one interactively.

---

#### `setup_create_project`

Interactive project creation.

**Parameters:**
| Name | Type | Required | Description |
|------|------|----------|-------------|
| code | string | yes | Short code (e.g., "MEAS-ERR") |
| name | string | yes | Full name |

**Returns:**
```json
{
  "success": true,
  "project": {
    "code": "MEAS-ERR",
    "name": "Measurement Error in Biomedical Science",
    "zotero_collection_key": "ABC123"
  },
  "user_actions_required": [
    "Create Google Drive folder: Literature/MEAS-ERR/",
    "Create NotebookLM notebook when ready (suggested: 'MEAS-ERR - Paper - [descriptor]')"
  ]
}
```

---

## Setup Wizard Flow

The setup wizard uses Claude's todo list feature to track progress. The agent **executes commands directly** where possible and only prompts the user for actions that require manual intervention (browser, GUI, pasting secrets).

**Key principle:** Google Drive and Zotero sync across machines, so the wizard should **detect existing setup** before creating anything new.

### What Syncs vs. Per-Machine

| Syncs Automatically | Per-Machine Setup Required |
|---------------------|---------------------------|
| Literature/ folder structure | Python/uv installation |
| Literature/.litrev/config.yaml | litrev-mcp package |
| PDFs in project folders | Environment variables (API keys) |
| Zotero collections & papers | Claude Code MCP config |
| Zotero tags & citation keys | |

### What Agent Executes vs. User Actions

| Task | Agent Executes | User Does |
|------|----------------|-----------|
| Check Python version | ✓ `python3 --version` | — |
| Install Python | ✓ `brew install python@3.11` (macOS) | — |
| Install uv | ✓ `curl -LsSf https://astral.sh/uv/install.sh \| sh` | — |
| Install litrev-mcp | ✓ `uv tool install ...` | — |
| Detect Google Drive path | ✓ Check common locations | Confirm or provide path |
| Check if Literature/ exists | ✓ Check Drive path | — |
| Check if config exists | ✓ Read `.litrev/config.yaml` | — |
| Create Literature/ folder | — | Create in Google Drive (if missing) |
| Create .litrev/config.yaml | ✓ Write file (if missing) | — |
| Create Zotero API key | — | Go to website, click buttons |
| Provide API key | — | Paste key into chat |
| Set environment variables | ✓ Append to shell config | Reload shell |
| Install Better BibTeX | — | Download, install in Zotero GUI |
| Create project Drive folder | — | Create in Google Drive (if missing) |
| Create NotebookLM notebook | — | Create in NotebookLM |
| Configure Claude Code MCP | ✓ Edit config file | Restart Claude Code |
| Create Zotero collection | ✓ Via API | — |

### Setup Detection Logic

```
Agent checks (in order):

1. Is Google Drive accessible?
   → Find path: ~/Library/CloudStorage/GoogleDrive-*/My Drive/ (macOS)
   → Or check LITREV_DRIVE_PATH env var
   
2. Does Literature/ folder exist?
   → Yes: Previous setup likely exists, check for config
   → No: Fresh setup needed, user must create folder
   
3. Does Literature/.litrev/config.yaml exist?
   → Yes: Load it — we have project definitions from another machine
   → No: Create it after Literature/ folder exists

4. Does Zotero have matching collections?
   → Cross-reference config projects with Zotero collections
   → Flag any mismatches

5. Are environment variables set on THIS machine?
   → ZOTERO_API_KEY, ZOTERO_USER_ID
   → These are per-machine even if config exists

6. Is Claude Code MCP configured on THIS machine?
   → Check claude_desktop_config.json
```

### Fresh Setup Sequence (First Machine)

```
User: Help me set up the literature review system

Agent: I'll check your system. First, looking for Google Drive...

[runs: ls ~/Library/CloudStorage/ | grep GoogleDrive]
Found: GoogleDrive-marcus@example.com

[runs: ls "~/Library/CloudStorage/GoogleDrive-marcus@example.com/My Drive/Literature" 2>/dev/null]
Literature folder not found — this appears to be a fresh setup.

Let me set up the tools first.

[runs: python3 --version]
✓ Python 3.11.5 found

[runs: which uv]
✗ uv not found — installing...

[runs: curl -LsSf https://astral.sh/uv/install.sh | sh]
✓ uv installed

[runs: uv tool install git+https://github.com/[user]/litrev-mcp]
✓ litrev-mcp installed

Now I need your Zotero credentials.

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Zotero API Key                       │
├─────────────────────────────────────────────────────────────┤
│ 1. Go to: https://www.zotero.org/settings/keys              │
│ 2. Click "Create new private key"                           │
│ 3. Check: Allow library access, notes, write access         │
│ 4. Save and copy the key                                    │
│                                                             │
│ Also note your User ID shown on that page.                  │
│ Paste both here.                                            │
└─────────────────────────────────────────────────────────────┘

User: Key is abc123xyz, user ID is 12345678

Agent: [runs: echo 'export ZOTERO_API_KEY="abc123xyz"' >> ~/.zshrc]
[runs: echo 'export ZOTERO_USER_ID="12345678"' >> ~/.zshrc]
✓ Added to ~/.zshrc

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Reload Shell                                │
├─────────────────────────────────────────────────────────────┤
│ Run: source ~/.zshrc                                        │
│ Then say "done".                                            │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: [verifies Zotero connection]
✓ Connected to Zotero! Library: "Marcus's Library"

Do you have Better BibTeX installed in Zotero?

User: Yes

Agent: ✓ Better BibTeX confirmed

Now let's create the Google Drive structure.

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Literature Folder                    │
├─────────────────────────────────────────────────────────────┤
│ In Google Drive (drive.google.com or Finder/Explorer):      │
│                                                             │
│ Create a folder called "Literature" at the root level       │
│                                                             │
│ Confirm when done.                                          │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: [runs: mkdir -p "~/Library/CloudStorage/GoogleDrive-.../My Drive/Literature/.litrev"]
[creates config.yaml with defaults]
✓ Config created at Literature/.litrev/config.yaml

This config will sync to any other machines via Google Drive.

[configures Claude Code MCP]
✓ MCP configuration added

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Restart Claude Code                         │
├─────────────────────────────────────────────────────────────┤
│ Quit and reopen Claude Code to load MCP tools.              │
│ Then say "hi" to verify.                                    │
└─────────────────────────────────────────────────────────────┘

[After restart...]

User: Hi

Agent: ✓ Tools loaded!

Let's create your first project. What's the code and name?

User: MEAS-ERR / Measurement Error in Biomedical Science

Agent: [creates Zotero collection via API]
[updates Literature/.litrev/config.yaml]

✓ Created:
  • Zotero collection: "Measurement Error in Biomedical Science"
  • Config updated (will sync to other machines)

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Project Folder                       │
├─────────────────────────────────────────────────────────────┤
│ In Google Drive, create:                                    │
│   Literature/MEAS-ERR/                                      │
│                                                             │
│ This is where you'll save PDFs for this project.            │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: 🎉 Setup complete!

Your setup will sync to other machines via Google Drive.
Try: "Search PubMed for measurement error glucose"
```

### Existing Setup Sequence (Second Machine)

```
User: Help me set up the literature review system

Agent: I'll check your system. Looking for Google Drive...

[runs: ls ~/Library/CloudStorage/ | grep GoogleDrive]
Found: GoogleDrive-marcus@example.com

[runs: ls "~/Library/CloudStorage/GoogleDrive-.../My Drive/Literature/"]
Found existing Literature folder with:
  .litrev/
  MEAS-ERR/
  MOD-SEL/

[runs: cat "Literature/.litrev/config.yaml"]
Found existing configuration with 2 projects:
  • MEAS-ERR: Measurement Error in Biomedical Science
  • MOD-SEL: Model Selection with Missing Data

✓ Found existing setup synced from another machine!

I just need to configure THIS machine. Let me check what's needed...

[runs: python3 --version]
✓ Python 3.11.5

[runs: which litrev-mcp]
✗ Not installed — installing...
[installs uv and litrev-mcp]

[runs: echo $ZOTERO_API_KEY]
✗ Not set on this machine

Your config synced, but API keys don't sync (for security).

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Provide Zotero Credentials                  │
├─────────────────────────────────────────────────────────────┤
│ You should have these from your original setup.             │
│ Check your password manager or:                             │
│ https://www.zotero.org/settings/keys                        │
│                                                             │
│ Paste your API key and User ID.                             │
│ (Or create a new key if needed.)                            │
└─────────────────────────────────────────────────────────────┘

User: Key is abc123xyz, user ID is 12345678

Agent: [sets env vars]
[verifies Zotero connection]
✓ Connected! Verified collections match config.

[configures Claude Code MCP]
✓ MCP configuration added

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Restart Claude Code                         │
├─────────────────────────────────────────────────────────────┤
│ Quit and reopen Claude Code to load MCP tools.              │
└─────────────────────────────────────────────────────────────┘

[After restart...]

User: Hi

Agent: ✓ This machine is now configured!

Your synced setup is ready:
  • 2 projects loaded from config
  • Zotero connection verified
  • All tools available

Try: "What's the status of MEAS-ERR?"
```

### Platform-Specific Commands (Agent Reference)

**Google Drive Path Detection:**
```bash
# macOS (Google Drive for Desktop)
ls ~/Library/CloudStorage/ | grep GoogleDrive
# Returns: GoogleDrive-user@gmail.com
# Full path: ~/Library/CloudStorage/GoogleDrive-user@gmail.com/My Drive/

# Linux (various clients)
# Common locations:
~/google-drive/
~/Google\ Drive/
~/.google-drive/

# Windows
# Common locations:
G:\My Drive\
C:\Users\{user}\Google Drive\
```

**Python Installation:**
```bash
# macOS
brew install python@3.11

# Ubuntu/Debian  
sudo apt update && sudo apt install python3.11 python3.11-venv

# Fedora
sudo dnf install python3.11

# Windows
winget install Python.Python.3.11
```

**uv Installation:**
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
irm https://astral.sh/uv/install.ps1 | iex
```

**Shell Config File Detection:**
```bash
# Detect user's shell
if [ -n "$ZSH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
elif [ -n "$BASH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
fi
```

**Claude Code Config Locations:**
```bash
# macOS
~/Library/Application\ Support/Claude/claude_desktop_config.json

# Linux
~/.config/Claude/claude_desktop_config.json

# Windows
%APPDATA%\Claude\claude_desktop_config.json
```

---

## Workflow Context

The agent should understand this workflow and guide users through it:

### Research is Iterative, Not Linear

The workflow is **cyclical**, not a pipeline:

```
        ┌──────────────────────────────────────────────────────┐
        │                                                      │
        │    "I need more on X..."                             │
        │    "This paper cites something relevant..."          │
        │    "Wait, what about Y?"                             │
        │                                                      │
        ▼                                                      │
    Discovery ──► Acquisition ──► Reading ──► Writing ─────────┘
        ▲              │            │           │
        │              │            │           │
        └──────────────┴────────────┴───────────┘
```

**Key behaviors:**
- Before searching externally, check existing insights first
- Writing often triggers new discovery needs
- Reading generates insights that inform future searches

### Knowledge Accumulation

AI-generated summaries and synthesis are **first-class artifacts**:

```
     ┌─────────┐    ┌─────────┐    ┌─────────┐
     │Consensus│    │NotebookLM│   │ Your    │
     │ search  │    │  query   │   │ notes   │
     └────┬────┘    └────┬─────┘   └────┬────┘
          │              │              │
          └──────────────┼──────────────┘
                         ▼
                 ┌───────────────┐
                 │ SAVE INSIGHT  │
                 └───────┬───────┘
                         │
                         ▼
          ┌──────────────────────────────┐
          │   INSIGHTS KNOWLEDGE BASE    │
          │                              │
          │   _notes/                    │
          │   ├── consensus_*.md         │
          │   ├── notebooklm_*.md        │
          │   └── synthesis_*.md         │
          └──────────────┬───────────────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       ┌────────┐  ┌──────────┐  ┌─────────┐
       │ Search │  │ Analyze  │  │ Detect  │
       │insights│  │ & answer │  │tensions │
       └────────┘  └──────────┘  └─────────┘
```

**Always save valuable AI outputs:**
- Consensus summaries with the query that produced them
- NotebookLM answers to specific questions
- Synthesis drafts and reading notes

### Paper Lifecycle

```
Found → Approved → In Zotero → PDF acquired → In NotebookLM
                   (_needs-pdf)  (_needs-notebooklm)  (_complete)
```

### Interaction Modes

| Mode | Agent Action | User Action |
|------|--------------|-------------|
| **Explore (Consensus)** | Provide search query | Execute search, report results |
| **Targeted search** | Execute via API (PubMed, ERIC, S2) | — |
| **Snowball** | Execute via Semantic Scholar API | — |
| **Add to Zotero** | Execute via API | — |
| **Acquire PDF** | Provide complete instructions (see below) | Download, attach to Zotero, save to Drive |
| **Add to NotebookLM** | Provide step-by-step instructions | Add from Drive, confirm |
| **Query NotebookLM** | Provide question | Execute query, report response |
| **Save insight** | Execute (save to _notes/) | Paste content from Consensus/NLM |
| **Query insights** | Execute (search/analyze _notes/) | — |

### PDF Acquisition Instructions Format

When telling the user to acquire a PDF, **always provide complete instructions for both storage locations**:

```
┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Acquire PDF                                 │
├─────────────────────────────────────────────────────────────┤
│ Paper: Measurement Error in Nonlinear Models                │
│ Authors: Carroll, Ruppert, Stefanski, Crainiceanu (2006)    │
│                                                             │
│ DOI URL: https://doi.org/10.1201/9781420010138              │
│                                                             │
│ 1. ZOTERO (primary):                                        │
│    • Download PDF from DOI link                             │
│    • In Zotero, right-click item → Add Attachment →         │
│      Attach Stored Copy of File                             │
│                                                             │
│ 2. GOOGLE DRIVE (for NotebookLM):                           │
│    • Save as: carroll_measurement_2006.pdf                  │
│    • Upload to: Literature/MEAS-ERR/                        │
│                                                             │
│ Confirm when done.                                          │
└─────────────────────────────────────────────────────────────┘
```

If multiple PDFs are pending, batch them:

```
┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Acquire 3 PDFs                              │
├─────────────────────────────────────────────────────────────┤
│ Project: MEAS-ERR                                           │
│ Drive folder: Literature/MEAS-ERR/                          │
│                                                             │
│ For each: attach to Zotero item AND save to Drive           │
│                                                             │
│ 1. Carroll et al. (2006)                                    │
│    DOI: https://doi.org/10.1201/9781420010138               │
│    Drive filename: carroll_measurement_2006.pdf             │
│                                                             │
│ 2. Fuller (1987)                                            │
│    DOI: https://doi.org/10.1002/9780470316665               │
│    Drive filename: fuller_measurement_1987.pdf              │
│                                                             │
│ 3. Buonaccorsi (2010)                                       │
│    DOI: https://doi.org/10.1201/9781420066586               │
│    Drive filename: buonaccorsi_measurement_2010.pdf         │
│                                                             │
│ Confirm when done (all or partial).                         │
└─────────────────────────────────────────────────────────────┘
```

### Autonomy Model

- **Autonomous:** Search APIs, search/analyze insights, save insights, summarize, recommend papers, update Zotero
- **Propose & wait:** Add to Zotero (confirm project), mark status changes
- **User executes:** PDF acquisition, Consensus searches, NotebookLM operations

### Agent Behaviors

**Before external search, check insights:**
```
User: "What's the best method for X?"

Agent behavior:
1. First: search_insights("X")
2. If found: synthesize from existing knowledge
3. If gap: then search PubMed/S2/suggest Consensus
```

**Always offer to save valuable outputs:**
```
User: [pastes Consensus or NotebookLM output]

Agent behavior:
1. Offer to save as insight
2. Extract papers mentioned
3. Check if papers already in Zotero
```

**Surface tensions proactively:**
```
Agent behavior when synthesizing:
1. Look for contradictions across sources
2. Flag with specific quotes
3. Suggest resolution paths (check source, query NLM, search for more)
```

---

## Example Interactions

### Example 1: Exploration

```
User: I want to explore measurement error correction in glucose data.

Agent: I'll help you build a literature base. Let's start with exploration.

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Search Consensus                            │
├─────────────────────────────────────────────────────────────┤
│ Query: "measurement error correction glucose clinical       │
│         data statistical methods"                           │
│                                                             │
│ Please report back:                                         │
│   1. The AI-generated summary                               │
│   2. Top 5 cited papers (title, authors, year, DOI)         │
└─────────────────────────────────────────────────────────────┘
```

### Example 2: Adding Papers

```
User: Add the Carroll 2006 book to MEAS-ERR

Agent: [calls zotero_add_paper with DOI lookup]

✓ Added to "Measurement Error in Biomedical Science":
  
  Carroll, Ruppert, Stefanski, Crainiceanu (2006)
  "Measurement Error in Nonlinear Models: A Modern Perspective"
  
  Citation key: carroll_measurement_2006
  Tagged: _needs-pdf

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Acquire PDF                                 │
├─────────────────────────────────────────────────────────────┤
│ DOI URL: https://doi.org/10.1201/9781420010138              │
│                                                             │
│ 1. ZOTERO: Download and attach to this item                 │
│    (Right-click → Add Attachment → Attach Stored Copy)      │
│                                                             │
│ 2. DRIVE: Save copy as carroll_measurement_2006.pdf         │
│    Upload to: Literature/MEAS-ERR/                          │
│                                                             │
│ Confirm when done.                                          │
└─────────────────────────────────────────────────────────────┘
```

### Example 3: Snowball

```
User: Do a backward snowball on that Carroll book

Agent: [calls semantic_scholar_references]

The Carroll book cites 312 papers. Here are the 10 most influential 
to measurement error methods:

1. Fuller (1987) - Measurement Error Models [2,341 citations]
2. ...

Want me to add any of these to MEAS-ERR?
```

### Example 4: Status Check

```
User: What's pending in my MEAS-ERR project?

Agent: [calls project_status]

MEAS-ERR Status:
├── Total papers: 42
├── Complete: 34
├── Needs PDF: 5
│   ├── smith_glucose_2019.pdf — doi:10.xxx
│   ├── jones_measurement_2021.pdf — doi:10.xxx
│   └── ...
└── Needs NotebookLM: 3
    ├── carroll_measurement_2006.pdf
    ├── fuller_measurement_1987.pdf
    └── buonaccorsi_measurement_2010.pdf

Ready to add 3 papers to NotebookLM from Drive folder 
"Literature/MEAS-ERR/". Want instructions?
```

### Example 5: Citation Key Lookup While Writing

```
~/glucose-paper $ claude

User: I need to cite that Carroll measurement error book

Agent: [calls zotero_get_citation_key with title_search="Carroll measurement error"]

Citation key: @carroll_measurement_2006

For Quarto, use: @carroll_measurement_2006
Or with page: @carroll_measurement_2006[p. 45]

Full BibTeX entry:
  @book{carroll_measurement_2006,
    author = {Carroll, Raymond J. and Ruppert, David and 
              Stefanski, Leonard A. and Crainiceanu, Ciprian M.},
    title = {Measurement Error in Nonlinear Models: A Modern Perspective},
    year = {2006},
    publisher = {Chapman and Hall/CRC},
    edition = {2nd}
  }
```

### Example 6: Multiple Citation Lookup

```
User: What are the cite keys for papers about OGTT in my library?

Agent: [calls zotero_search with query="OGTT"]

Found 4 papers matching "OGTT":

1. @bergman_minimal_1979 — "Quantitative estimation of insulin sensitivity"
2. @mari_meal_2001 — "A model-based method for assessing insulin sensitivity"
3. @cobelli_glucose_2009 — "The oral minimal model method"
4. @dalla_simple_2005 — "A simple method for estimating insulin sensitivity"

Need the full BibTeX for any of these?
```

### Example 7: Confirming PDF Acquisition

```
User: I got the PDFs for Carroll and Fuller

Agent: [calls zotero_update_status for both]

✓ Updated status:
  • carroll_measurement_2006.pdf — _needs-pdf → _needs-notebooklm
  • fuller_measurement_1987.pdf — _needs-pdf → _needs-notebooklm

Confirm you saved them to Drive as:
  • Literature/MEAS-ERR/carroll_measurement_2006.pdf
  • Literature/MEAS-ERR/fuller_measurement_1987.pdf

Ready to add to NotebookLM?

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Add to NotebookLM                           │
├─────────────────────────────────────────────────────────────┤
│ Notebook: MEAS-ERR - Paper - Glucose OGTT methods           │
│                                                             │
│ In NotebookLM:                                              │
│   1. Click "Add Source"                                     │
│   2. Select "Google Drive"                                  │
│   3. Navigate to Literature/MEAS-ERR/                       │
│   4. Select:                                                │
│      • carroll_measurement_2006.pdf                         │
│      • fuller_measurement_1987.pdf                          │
│                                                             │
│ The source names will match your citation keys.             │
│ Confirm when done.                                          │
└─────────────────────────────────────────────────────────────┘
```

### Example 8: First-Time Setup

```
User: Help me set up the literature review system

Agent: I'll check your system. First, looking for Google Drive...

[runs: ls ~/Library/CloudStorage/ | grep GoogleDrive]
Found: GoogleDrive-marcus@example.com

[runs: ls "~/Library/CloudStorage/GoogleDrive-marcus@example.com/My Drive/Literature" 2>/dev/null]
Literature folder not found — this is a fresh setup.

Let me install the tools first.

[runs: python3 --version]
✓ Python 3.11.5 found

[runs: which uv]
✗ Not found — installing...

[runs: curl -LsSf https://astral.sh/uv/install.sh | sh]
✓ uv installed

[runs: uv tool install git+https://github.com/[user]/litrev-mcp]
✓ litrev-mcp installed

Here's where we stand:

☑ Python 3.11.5
☑ uv installed
☑ litrev-mcp installed
☐ Zotero API key — need your input
☐ Environment variables — I'll set after you provide key
☐ Better BibTeX — need to verify
☐ Google Drive Literature folder — need your action
☐ Claude Code MCP config — I'll set this
☐ First project

Let's get your Zotero credentials.

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Zotero API Key                       │
├─────────────────────────────────────────────────────────────┤
│ 1. Go to: https://www.zotero.org/settings/keys              │
│ 2. Click "Create new private key"                           │
│ 3. Check: Allow library access, notes, write access         │
│ 4. Save and copy the key                                    │
│                                                             │
│ Also note your User ID shown on that page.                  │
│ Paste both here.                                            │
└─────────────────────────────────────────────────────────────┘

User: Key is abc123xyz, user ID is 12345678

Agent: [runs: echo 'export ZOTERO_API_KEY="abc123xyz"' >> ~/.zshrc]
[runs: echo 'export ZOTERO_USER_ID="12345678"' >> ~/.zshrc]
✓ Added to ~/.zshrc

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Reload Shell                                │
├─────────────────────────────────────────────────────────────┤
│ Run: source ~/.zshrc                                        │
│ Then say "done".                                            │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: [verifies Zotero connection]
✓ Connected! Library: "Marcus's Library" (3 collections, 127 items)

Do you have Better BibTeX installed in Zotero?

User: Yes

Agent: ✓ Better BibTeX confirmed

Now let's set up Google Drive.

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Literature Folder                    │
├─────────────────────────────────────────────────────────────┤
│ In Google Drive, create a folder called "Literature"        │
│ at the root level.                                          │
│                                                             │
│ Confirm when done.                                          │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: [runs: mkdir -p "~/Library/CloudStorage/GoogleDrive-.../My Drive/Literature/.litrev"]
[creates config.yaml with defaults]
✓ Config created at Literature/.litrev/config.yaml
  (This will sync to other machines via Google Drive)

[configures Claude Code MCP]
✓ MCP configuration added

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Restart Claude Code                         │
├─────────────────────────────────────────────────────────────┤
│ Quit Claude Code completely and reopen it.                  │
│ Then say "hi" to verify.                                    │
└─────────────────────────────────────────────────────────────┘

User: Hi, I'm back

Agent: [calls setup_check]
✓ All litrev-mcp tools available!

Let's create your first project.
What's the code and full name?

User: MEAS-ERR / Measurement Error in Biomedical Science

Agent: [creates Zotero collection via API]
[updates Literature/.litrev/config.yaml]

✓ Created:
  • Zotero collection: "Measurement Error in Biomedical Science" 
  • Config updated (will sync to other machines)

┌─────────────────────────────────────────────────────────────┐
│ ACTION FOR YOU: Create Project Folder                       │
├─────────────────────────────────────────────────────────────┤
│ In Google Drive, create:                                    │
│   Literature/MEAS-ERR/                                      │
│                                                             │
│ This is where you'll save PDFs for this project.            │
└─────────────────────────────────────────────────────────────┘

User: Done

Agent: 
☑ Python 3.11.5
☑ uv installed
☑ litrev-mcp installed
☑ Zotero API configured
☑ Environment variables set
☑ Better BibTeX installed
☑ Google Drive ready (config syncs across machines)
☑ Claude Code MCP configured
☑ Project MEAS-ERR created

🎉 Setup complete!

On your next machine, just run setup again — it will detect
the existing Literature folder and config, and only set up
the per-machine items (env vars, MCP config).

Try: "Search PubMed for measurement error glucose"
```

### Example 9: Saving a Consensus Summary

```
User: I just searched Consensus for "glucose measurement error 
      correction methods in longitudinal studies" — here's the 
      synthesis it gave me:

      "Measurement error in glucose data can be addressed through 
      several statistical approaches. SIMEX (Simulation Extrapolation) 
      is commonly used when the error variance is known. Regression 
      calibration is preferred when validation data is available..."

Agent: I'll save this to your MEAS-ERR insights.

[calls save_insight]

✓ Saved to: Literature/MEAS-ERR/_notes/2024-01-15_consensus_glucose_correction_methods.md

The note includes:
  • Your original query
  • The synthesis
  • Date captured

I noticed several papers mentioned. Want me to check if any are 
already in your Zotero, or search for them?
```

### Example 10: Querying Saved Knowledge

```
User: When should I use SIMEX vs regression calibration?

Agent: Let me check what you've already learned about this.

[calls analyze_insights with mode="answer"]

Based on your saved insights from 3 sources:

**Use SIMEX when:**
- Measurement error distribution is known (Consensus, Jan 15)
- Functional form is complex/nonlinear (NotebookLM, Jan 18)
- You have repeated measures available (your synthesis, Jan 20)

**Use regression calibration when:**
- You have validation data (Consensus, Jan 15)
- Linear or approximately linear relationships (NotebookLM, Jan 18)
- Computational simplicity is important (your synthesis, Jan 20)

⚠️ **Tension detected:**
Your Consensus note says SIMEX needs n > 500, but your NotebookLM 
note (citing Carroll 2006) says n > 200 is sufficient.

**To resolve:** Want me to give you a question to ask NotebookLM 
directly about Carroll's sample size recommendations?
```

### Example 11: Detecting Contradictions

```
User: Are there any contradictions in what I've learned about 
      measurement error correction?

Agent: [calls analyze_insights with mode="tensions"]

I found 2 tensions across your MEAS-ERR insights:

**1. Sample size for SIMEX**
   • Consensus (Jan 15): "n > 500 recommended"
   • NotebookLM (Jan 18): "Carroll suggests n > 200"
   
   📍 Resolution path: The Consensus source may be citing a 
   different paper or context. Check Carroll Ch. 5 directly.

**2. When regression calibration fails**
   • Consensus (Jan 15): "fails with heteroscedastic error"
   • Your synthesis (Jan 20): "can handle heteroscedastic error 
     with weighted approach"
   
   📍 Resolution path: Both may be correct — standard vs. 
   weighted variants. Want me to search for papers on weighted 
   regression calibration?

---

**No tensions found on:**
- Basic definitions
- General guidance on when to use each method
- Software implementations
```

### Example 12: Mid-Writing Discovery Loop

```
User: I'm writing the methods section and realized I don't have 
      anything on bootstrap confidence intervals for measurement 
      error models

Agent: Let me check your insights and Zotero.

[calls search_insights with "bootstrap confidence interval"]

No insights found on this topic.

[calls zotero_search with "bootstrap confidence interval"]

You have 1 paper that mentions this:
  • @carroll_measurement_2006 (may cover in Chapter 8)

[calls semantic_scholar_search]

Found 12 relevant papers. Top 3 by citation count:

1. Efron & Tibshirani (1994) - foundational bootstrap text [15,420 cites]
2. Carpenter & Bithell (2000) - bootstrap CI review [2,103 cites]
3. Wang & Wang (2015) - bootstrap for measurement error [89 cites]

Want me to:
1. Add any of these to MEAS-ERR?
2. Give you a NotebookLM question to ask about Carroll Ch. 8?
```

### Example 13: Building From Insights

```
User: I want to write a paragraph comparing the three main 
      measurement error correction approaches

Agent: [calls analyze_insights]

From your insights, you've covered:
  ✓ SIMEX (3 notes)
  ✓ Regression calibration (3 notes)  
  ✗ MIME/multiple imputation (no notes found)

Here's a draft based on what you've learned:

---
Three primary approaches exist for measurement error correction 
in regression models. SIMEX (Simulation Extrapolation) is preferred 
when the error distribution is known but functional forms are 
complex [@stefanski_simex_1995; @carroll_measurement_2006]. 
Regression calibration offers a simpler alternative when validation 
data is available and relationships are approximately linear 
[@carroll_measurement_2006]. **[GAP: You haven't captured insights 
about the third approach — multiple imputation methods.]**
---

Want me to:
1. Search for papers on multiple imputation for measurement error?
2. Give you a Consensus query to fill this gap?
```

### Example 14: What Do I Know About X?

```
User: What do I know about glucose measurement error specifically?

Agent: [calls search_insights with query="glucose"]

You have 4 insights mentioning glucose in MEAS-ERR:

**From Consensus (2 notes):**
- Glucose OGTT has ~5-8% CV in typical lab conditions
- Fasting glucose more reliable than post-load measures
- Key papers mentioned: Ferrannini 1998, Bland & Altman 1986

**From NotebookLM (1 note):**
- Carroll recommends functional measurement error models for 
  glucose due to physiological variation
- Discussed in @carroll_measurement_2006 Ch. 12

**From your synthesis (1 note):**
- Your conclusion: "Use replicate measures when possible, SIMEX 
  as fallback"

Want me to compile these into a single summary note?
```

---

## Installation & Configuration

### For Users (README content)

**Prerequisites:** The setup wizard will walk you through everything, but here's the overview:

1. Python 3.10+ 
2. Zotero with Better BibTeX plugin
3. Google Drive folder structure
4. Claude Code with MCP configured

### Quick Start

```bash
# In Claude Code, just ask:
> Help me set up the literature review system

# The agent will:
# 1. Check what's installed
# 2. Create a todo list of setup steps
# 3. Walk you through each step interactively
```

### Manual Installation (if preferred)

```bash
# 1. Ensure Python 3.10+ is installed
python3 --version

# 2. Install uv (recommended) or use pip
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install litrev-mcp
uv tool install git+https://github.com/[username]/litrev-mcp.git
# OR with pip:
pip install git+https://github.com/[username]/litrev-mcp.git

# 4. Set environment variables (add to ~/.zshrc or ~/.bashrc)
export ZOTERO_API_KEY="your-key-here"
export ZOTERO_USER_ID="your-user-id"
export NCBI_API_KEY="your-ncbi-key"  # optional, improves PubMed rate limit

# 5. Add to Claude Code MCP config
# Location varies by OS - see setup wizard for exact path
# Add to mcpServers section:
{
  "mcpServers": {
    "litrev": {
      "command": "litrev-mcp",
      "args": []
    }
  }
}

# 6. Restart Claude Code

# 7. Verify
> Run setup_check to verify configuration
```

### New Machine Setup

When you clone to a new machine, you only need to:

1. Install Python (if not present)
2. Install litrev-mcp package
3. Set environment variables (API keys)
4. Configure Claude Code MCP

Everything else (projects, papers, PDFs) syncs via Zotero and Google Drive.

---

## Error Handling

All tools should return structured errors:

```json
{
  "success": false,
  "error": {
    "code": "ZOTERO_AUTH_FAILED",
    "message": "Could not authenticate with Zotero. Check your API key.",
    "suggestion": "Run setup_check to verify configuration."
  }
}
```

Common error codes:
- `ZOTERO_AUTH_FAILED` — API key invalid
- `ZOTERO_NOT_FOUND` — Collection or item not found
- `PUBMED_RATE_LIMITED` — Too many requests
- `SEMANTIC_SCHOLAR_NOT_FOUND` — Paper not in S2 database
- `CONFIG_MISSING` — Required configuration not present
- `PROJECT_NOT_FOUND` — Project code not in config

---

## Testing

Include tests for:
1. Each tool with mocked API responses
2. Configuration loading
3. Error handling paths
4. Status tag transitions

---

## Future Enhancements (Out of Scope for MVP)

- Web of Science integration (pending API approval)
- Automatic DOI lookup from title
- PDF download automation via Unpaywall API
- NotebookLM Enterprise API integration
- Citation graph visualization
- Duplicate detection across projects
