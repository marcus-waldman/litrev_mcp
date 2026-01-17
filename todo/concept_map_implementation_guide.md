# Concept Map Implementation Guide

## Overview

This document specifies the implementation of a **concept map** feature for litrev-mcp. The concept map enables the AI collaborator to organize knowledge from collected literature, weighted by salience relative to the user's purpose.

## Core Design

### Three-Layer Architecture

```
+-----------------------------------------------------------+
|                     Salience Map                           |
|              "What matters for my purpose"                 |
|         (computed at query-time based on goal/audience)    |
+-----------------------------------------------------------+
                            |
                            v
          +-----------------+------------------+
          |                                    |
          v                                    v
+---------------------+             +----------------------+
|    Concept Map      |             |    AI's General      |
|  (from literature)  |             |      Knowledge       |
|                     |             |                      |
|  "What we have"     |             | "What should exist"  |
| (grounded in papers)|             | (structural scaffold)|
+---------------------+             +----------------------+
          |                                    |
          +----------------+-------------------+
                           |
                           v
                    +-----------+
                    |    GAP    |
                    |           |
                    | Salient   |
                    | but not   |
                    | grounded  |
                    +-----------+
```

### Key Properties

1. **Concept Map** - Built from insights + AI general knowledge
   - Grounded evidence from your literature (has citations)
   - Structural relationships from AI knowledge (scaffolding, could be wrong)
   - Every piece tagged with epistemic status

2. **Salience** - Computed at query-time, not static
   - Changes based on what you're asking
   - Weighted by purpose/audience/argument
   - Determines what matters for the current problem

3. **Gaps** - Mismatch between salient and grounded
   - AI knowledge suggests what should exist
   - Concept map shows what you have
   - Gap = salient concept without evidence

---

## Data Model

### Concept Node Structure

```yaml
concept:
  id: "reg_dilution"                    # Unique identifier
  name: "Regression Dilution"           # Human-readable name
  definition: "Attenuation of..."       # Brief definition
  aliases: ["dilution bias", "attenuation bias"]

  # Epistemic status
  source: "insight" | "ai_knowledge"    # Where this concept came from

  # Grounded evidence (from your literature)
  evidence:
    - insight_id: "hutcheon2010_summary"
      claim: "Can bias HRs by 10-50%"
      pages: [3, 7-8]
    - insight_id: "frost2000_methods"
      claim: "Correction requires repeat measurements"

  # Relationships to other concepts
  relationships:
    - type: "caused_by"
      target: "classical_measurement_error"
      source: "ai_knowledge"           # No evidence yet
      grounded_in: null
    - type: "corrected_by"
      target: "regression_calibration"
      source: "insight"                # Has evidence
      grounded_in: "hutcheon2010_summary"
```

### Relationship Types

| Type | Meaning | Example |
|------|---------|---------|
| `caused_by` | X results from Y | dilution <- measurement error |
| `corrected_by` | X is addressed by method Y | dilution <- regression calibration |
| `type_of` | X is a subtype of Y | Berkson error <- measurement error |
| `requires` | X depends on Y | regression calibration <- reliability estimate |
| `assumes` | X assumes Y holds | SIMEX <- non-differential error |
| `contradicts` | Paper A vs Paper B on X | claim conflicts |
| `related_to` | General association | looser connection |

---

## Database Schema (DuckDB)

### Tables

```sql
-- Global concept storage (shared across projects)
CREATE TABLE concepts (
    id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    definition TEXT,
    source VARCHAR NOT NULL,          -- 'insight' or 'ai_knowledge'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Concept aliases for flexible matching
CREATE TABLE concept_aliases (
    concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    alias VARCHAR NOT NULL,
    PRIMARY KEY (concept_id, alias)
);

-- Project-specific concept links (with salience)
-- Same concept can exist in multiple projects with different salience
CREATE TABLE project_concepts (
    project VARCHAR NOT NULL,
    concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    salience_weight FLOAT DEFAULT 0.5,  -- Project-specific importance (0-1)
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project, concept_id)
);

-- Relationships between concepts (global)
CREATE TABLE concept_relationships (
    id INTEGER PRIMARY KEY,
    from_concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    to_concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    relationship_type VARCHAR NOT NULL,
    source VARCHAR NOT NULL,          -- 'insight' or 'ai_knowledge'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(from_concept_id, to_concept_id, relationship_type)
);

-- Evidence linking concepts to insights (project-specific)
-- This is where grounding happens - evidence is always project-specific
CREATE TABLE concept_evidence (
    id INTEGER PRIMARY KEY,
    concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    project VARCHAR NOT NULL,
    insight_id VARCHAR NOT NULL,      -- References insight filename
    claim TEXT NOT NULL,
    pages VARCHAR,                    -- Optional page numbers
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Conflict tracking (when AI scaffolding contradicts evidence)
CREATE TABLE concept_conflicts (
    id INTEGER PRIMARY KEY,
    concept_id VARCHAR NOT NULL REFERENCES concepts(id),
    project VARCHAR NOT NULL,
    ai_claim TEXT NOT NULL,           -- What AI knowledge suggests
    evidence_claim TEXT NOT NULL,     -- What literature says
    insight_id VARCHAR NOT NULL,      -- Source of contradiction
    status VARCHAR DEFAULT 'unresolved',  -- 'unresolved', 'ai_correct', 'evidence_correct', 'both_valid'
    resolution_note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_project_concepts_project ON project_concepts(project);
CREATE INDEX idx_relationships_from ON concept_relationships(from_concept_id);
CREATE INDEX idx_relationships_to ON concept_relationships(to_concept_id);
CREATE INDEX idx_relationships_type ON concept_relationships(relationship_type);
CREATE INDEX idx_evidence_concept ON concept_evidence(concept_id);
CREATE INDEX idx_evidence_project ON concept_evidence(project);
CREATE INDEX idx_conflicts_project ON concept_conflicts(project);
CREATE INDEX idx_conflicts_status ON concept_conflicts(status);
```

### Schema Notes

- **concepts**: Global - same concept can be referenced by multiple projects
- **project_concepts**: Links projects to concepts with project-specific salience weights
- **concept_relationships**: Global - relationships are domain knowledge, not project-specific
- **concept_evidence**: Project-specific - evidence comes from specific project's literature
- **concept_conflicts**: Tracks contradictions between AI scaffolding and grounded evidence

### Database Location

Store in existing DuckDB file: `Literature/.litrev/literature.duckdb`

This keeps all project data together and allows joins with existing `papers` and `chunks` tables.

---

## New Tools

### 1. `extract_concepts`

**Purpose**: Extract concepts and relationships from an insight using AI

**Input**:
```json
{
  "project": "MEAS-ERR",
  "insight_id": "hutcheon2010_summary",
  "content": "Full text of the insight (optional, will read from file if not provided)"
}
```

**Behavior**:
1. Read insight content (from file or parameter)
2. Use AI to identify:
   - Concepts mentioned (with definitions)
   - Relationships between concepts
   - Claims that could serve as evidence
3. Cross-reference with AI's general knowledge to add structural relationships
4. Return proposed additions for user confirmation

**Output**:
```json
{
  "success": true,
  "project": "MEAS-ERR",
  "insight_id": "hutcheon2010_summary",
  "extracted": {
    "concepts": [
      {
        "id": "reg_dilution",
        "name": "Regression Dilution",
        "definition": "...",
        "source": "insight",
        "is_new": true
      }
    ],
    "relationships": [
      {
        "from": "reg_dilution",
        "to": "meas_error",
        "type": "caused_by",
        "source": "ai_knowledge"
      }
    ],
    "evidence": [
      {
        "concept_id": "reg_dilution",
        "claim": "Can bias HRs by 10-50%"
      }
    ]
  },
  "prompt": "Add these to concept map? Use add_concepts to confirm."
}
```

### 2. `add_concepts`

**Purpose**: Add extracted concepts to the concept map (after user confirmation)

**Input**:
```json
{
  "project": "MEAS-ERR",
  "concepts": [...],
  "relationships": [...],
  "evidence": [...]
}
```

**Behavior**:
1. Validate all inputs
2. Insert/update concepts (upsert by id)
3. Insert relationships
4. Insert evidence
5. Return summary of changes

### 3. `query_concepts`

**Purpose**: Query the concept map with salience weighting

**Input**:
```json
{
  "project": "MEAS-ERR",
  "query": "What methods correct for measurement error?",
  "purpose": "Methods section for epidemiology journal",
  "audience": "Reviewers familiar with regression but not measurement error correction",
  "max_results": 10
}
```

**Behavior**:
1. Parse query to identify relevant concept types/relationships
2. Compute salience weights based on purpose/audience
3. Traverse concept graph with salience weighting
4. Return concepts ordered by salience, with evidence
5. Flag concepts that are AI scaffolding (ungrounded)

**Output**:
```json
{
  "success": true,
  "query": "...",
  "results": [
    {
      "concept": "regression_calibration",
      "salience": 0.95,
      "grounded": true,
      "evidence": ["Reduces bias by 80-90% (hutcheon2010)"],
      "related_via": "corrected_by <- regression_dilution"
    },
    {
      "concept": "simex",
      "salience": 0.82,
      "grounded": false,
      "evidence": [],
      "note": "AI scaffolding - consider finding literature"
    }
  ]
}
```

### 4. `find_concept_gaps`

**Purpose**: Identify salient concepts that lack grounded evidence

**Input**:
```json
{
  "project": "MEAS-ERR",
  "purpose": "Methods section on measurement error correction",
  "audience": "Epidemiology journal reviewers"
}
```

**Behavior**:
1. Identify concepts that should be salient given purpose/audience
2. Check which are grounded vs AI scaffolding
3. Use AI knowledge to suggest what's missing entirely
4. Return prioritized list of gaps

**Output**:
```json
{
  "success": true,
  "gaps": [
    {
      "concept": "simex",
      "status": "ai_scaffolding",
      "why_salient": "Alternative to regression calibration, reviewers may ask about it",
      "suggestion": "Search for SIMEX measurement error papers"
    },
    {
      "concept": "differential_error",
      "status": "missing",
      "why_salient": "Your current literature assumes non-differential error, but you should address this assumption",
      "suggestion": "Add papers discussing differential measurement error"
    }
  ]
}
```

### 5. `show_concept_map`

**Purpose**: Display current concept map structure

**Input**:
```json
{
  "project": "MEAS-ERR",
  "format": "summary" | "detailed",
  "filter_source": "all" | "grounded" | "ai_knowledge"
}
```

**Output**: Human-readable text representation of concept map state

### 6. `visualize_concept_map`

**Purpose**: Generate interactive PyVis graph visualization

**Input**:
```json
{
  "project": "MEAS-ERR",
  "output_path": "optional/path/to/output.html",
  "filter_source": "all" | "grounded" | "ai_knowledge",
  "highlight_gaps": true,
  "show_salience": true
}
```

**Behavior**:
1. Query concept graph for project
2. Build PyVis network:
   - Nodes = concepts (color by source: grounded=green, ai_knowledge=yellow, gap=red)
   - Edges = relationships (labeled with type)
   - Node size = salience weight
   - Tooltips show definition and evidence
3. Generate interactive HTML file
4. Return path to generated file

**Output**:
```json
{
  "success": true,
  "project": "MEAS-ERR",
  "output_path": "Literature/MEAS-ERR/_concept_map.html",
  "stats": {
    "total_concepts": 15,
    "grounded": 8,
    "ai_scaffolding": 5,
    "gaps": 2,
    "relationships": 23
  }
}
```

**PyVis Configuration**:
```python
from pyvis.network import Network

net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="black")
net.barnes_hut()  # Physics for layout

# Node colors by source
colors = {
    'grounded': '#4CAF50',      # Green - has evidence
    'ai_knowledge': '#FFC107',  # Yellow/amber - scaffolding
    'gap': '#F44336',           # Red - missing but salient
}

# Add nodes with attributes
for concept in concepts:
    net.add_node(
        concept['id'],
        label=concept['name'],
        title=f"{concept['definition']}\n\nEvidence: {concept['evidence_count']}",
        color=colors[concept['source']],
        size=concept['salience'] * 30 + 10,  # Scale by salience
    )

# Add edges with relationship labels
for rel in relationships:
    net.add_edge(
        rel['from'],
        rel['to'],
        title=rel['type'],
        label=rel['type'],
    )

net.save_graph(output_path)
```

### 7. `update_concept`

**Purpose**: Manually update a concept (definition, relationships, etc.)

**Input**:
```json
{
  "project": "MEAS-ERR",
  "concept_id": "reg_dilution",
  "updates": {
    "definition": "Updated definition...",
    "add_alias": "dilution effect",
    "add_relationship": {
      "type": "related_to",
      "target": "reliability",
      "source": "insight",
      "grounded_in": "frost2000_methods"
    }
  }
}
```

### 8. `delete_concept`

**Purpose**: Remove a concept and its relationships

**Input**:
```json
{
  "project": "MEAS-ERR",
  "concept_id": "wrong_concept",
  "confirm": true
}
```

### 9. `resolve_conflict`

**Purpose**: Resolve a flagged conflict between AI scaffolding and grounded evidence

**Input**:
```json
{
  "conflict_id": 123,
  "resolution": "ai_correct" | "evidence_correct" | "both_valid",
  "note": "Optional explanation of resolution"
}
```

**Behavior**:
1. Update conflict status
2. If ai_correct: keep AI scaffolding, note evidence as exception
3. If evidence_correct: update concept to match evidence
4. If both_valid: keep both, add nuance to concept definition

### 10. `list_conflicts`

**Purpose**: Show unresolved conflicts for review

**Input**:
```json
{
  "project": "MEAS-ERR",
  "status": "unresolved" | "all"
}
```

---

## Integration Points

### 1. Enhance `save_insight`

After saving an insight, automatically trigger concept extraction:

```python
# In save_insight(), after writing the file:
if config.concept_map.auto_extract:
    extraction = await extract_concepts(
        project=project,
        insight_id=insight_id,
        content=content
    )
    result['concept_extraction'] = extraction
    result['guidance']['next_steps'].append(
        'Review extracted concepts and add to concept map'
    )
```

### 2. Enhance `ask_papers`

Use concept map to improve retrieval and synthesis:

```python
# In ask_papers(), before RAG search:
if concept_map_exists(project):
    # Get relevant concepts for query
    relevant_concepts = await query_concepts(
        project=project,
        query=question,
        purpose=context.get('goal'),
        audience=context.get('audience')
    )

    # Augment RAG results with concept context
    result['concept_context'] = relevant_concepts
    result['gaps'] = [c for c in relevant_concepts if not c['grounded']]
```

### 3. Workflow Guidance

Add concept map suggestions to workflow guidance:

```python
if config.workflow.show_guidance:
    result['guidance'] = {
        'next_steps': [
            'Review extracted concepts',
            'Check for gaps with find_concept_gaps',
            'Ground AI scaffolding with additional literature'
        ],
        'concept_map_status': f'{grounded_count} grounded, {scaffold_count} scaffolding'
    }
```

---

## Configuration

Add to `config.py`:

```python
class ConceptMapConfig(BaseModel):
    """Configuration for concept map feature."""
    enabled: bool = True
    auto_extract: bool = True           # Auto-extract from new insights
    show_scaffolding: bool = True       # Show AI knowledge in queries
    salience_threshold: float = 0.3     # Min salience to include in results

class Config(BaseModel):
    # ... existing fields ...
    concept_map: ConceptMapConfig = ConceptMapConfig()
```

---

## File Structure

```
Literature/
├── .litrev/
│   ├── config.yaml
│   └── literature.duckdb          # Concept tables added here
├── {PROJECT}/
│   ├── _notes/                    # Insights (source for concepts)
│   ├── _concept_map.md            # Optional: human-readable export
│   └── ...
```

---

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Add database tables to existing `literature.duckdb`
- [ ] Create `src/litrev_mcp/tools/concept_map_db.py` with CRUD operations
- [ ] Add `ConceptMapConfig` to `config.py`
- [ ] Add `pyvis` to dependencies

### Phase 2: Basic Tools (CRUD)
- [ ] Implement `add_concepts` - add concepts to global library + project
- [ ] Implement `show_concept_map` - text representation
- [ ] Implement `update_concept` - modify definitions, relationships
- [ ] Implement `delete_concept` - remove with confirmation
- [ ] Register tools in `server.py`

### Phase 3: AI-Powered Extraction (Use Opus)
- [ ] Implement `extract_concepts` with Claude Opus
- [ ] Design extraction prompt for:
  - Concept identification with definitions
  - Relationship extraction (typed)
  - Claims extraction for evidence
- [ ] Add structural scaffolding from AI general knowledge
- [ ] Integrate with `save_insight` for automatic extraction

### Phase 4: Salience & Querying
- [ ] Implement hybrid salience computation:
  - Embedding similarity for initial ranking
  - AI reasoning for refinement
- [ ] Implement `query_concepts` with salience weighting
- [ ] Implement `find_concept_gaps` - compare salient vs grounded

### Phase 5: Conflict Management
- [ ] Implement conflict detection during extraction
- [ ] Implement `list_conflicts` - show unresolved conflicts
- [ ] Implement `resolve_conflict` - human resolution workflow

### Phase 6: Visualization
- [ ] Implement `visualize_concept_map` with PyVis
- [ ] Color coding: green=grounded, yellow=scaffolding, red=gap
- [ ] Node size by salience, tooltips with evidence
- [ ] Interactive HTML output

### Phase 7: Integration & Enhancement
- [ ] Modify `save_insight` to auto-extract (fully automatic)
- [ ] Modify `ask_papers` to use concept context
- [ ] Add workflow guidance for concept map
- [ ] Cross-project concept sharing (hierarchical)

### Phase 8: Testing & Refinement
- [ ] Unit tests for database operations
- [ ] Integration tests for extraction with Opus
- [ ] Test salience computation with real queries
- [ ] Test conflict detection and resolution
- [ ] User testing and refinement

---

## Example Queries (Standard SQL)

### Find what corrects a concept

```sql
SELECT
    c2.name AS correction_method,
    r.source AS evidence_status,
    pc.salience_weight
FROM concept_relationships r
JOIN concepts c1 ON r.from_concept_id = c1.id
JOIN concepts c2 ON r.to_concept_id = c2.id
JOIN project_concepts pc ON c2.id = pc.concept_id
WHERE c1.name = 'Regression Dilution'
  AND r.relationship_type = 'corrected_by'
  AND pc.project = 'MEAS-ERR'
ORDER BY pc.salience_weight DESC;
```

### Get project concepts with evidence count

```sql
SELECT
    c.name,
    c.definition,
    c.source,
    pc.salience_weight,
    COUNT(DISTINCT e.id) AS evidence_count
FROM concepts c
JOIN project_concepts pc ON c.id = pc.concept_id
LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = pc.project
WHERE pc.project = 'MEAS-ERR'
GROUP BY c.id, c.name, c.definition, c.source, pc.salience_weight
ORDER BY pc.salience_weight DESC;
```

### Find concepts within N hops (recursive CTE)

```sql
WITH RECURSIVE paths AS (
    -- Base: direct connections
    SELECT
        r.from_concept_id AS start_id,
        r.to_concept_id AS end_id,
        1 AS hops
    FROM concept_relationships r
    JOIN concepts c ON r.from_concept_id = c.id
    WHERE c.name = 'Measurement Error'

    UNION ALL

    -- Recursive: one more hop
    SELECT
        p.start_id,
        r.to_concept_id,
        p.hops + 1
    FROM paths p
    JOIN concept_relationships r ON p.end_id = r.from_concept_id
    WHERE p.hops < 2
)
SELECT DISTINCT c.name, c.source, pc.salience_weight
FROM paths p
JOIN concepts c ON p.end_id = c.id
JOIN project_concepts pc ON c.id = pc.concept_id
WHERE c.name != 'Measurement Error'
  AND pc.project = 'MEAS-ERR';
```

### Find gaps (AI knowledge without evidence in project)

```sql
SELECT
    c.name,
    c.definition,
    pc.salience_weight
FROM concepts c
JOIN project_concepts pc ON c.id = pc.concept_id
LEFT JOIN concept_evidence e ON c.id = e.concept_id AND e.project = pc.project
WHERE pc.project = 'MEAS-ERR'
  AND c.source = 'ai_knowledge'
  AND e.concept_id IS NULL
  AND pc.salience_weight > 0.5  -- Only salient concepts
ORDER BY pc.salience_weight DESC;
```

### List unresolved conflicts

```sql
SELECT
    c.name AS concept,
    cf.ai_claim,
    cf.evidence_claim,
    cf.insight_id,
    cf.created_at
FROM concept_conflicts cf
JOIN concepts c ON cf.concept_id = c.id
WHERE cf.project = 'MEAS-ERR'
  AND cf.status = 'unresolved'
ORDER BY cf.created_at DESC;
```

---

## Design Decisions (Resolved)

1. **Salience Computation**: Hybrid approach
   - Use embedding similarity for initial ranking of concepts
   - AI reasoning for refinement based on purpose/audience context
   - Combine scores for final salience weighting

2. **AI Extraction**: Fully automatic with Opus
   - Concepts extracted automatically when insights are saved
   - No confirmation required - user can review/refine later
   - Reduces friction in workflow
   - **IMPORTANT**: Use Claude Opus for extraction (not Haiku/Sonnet)
   - Extraction requires nuanced understanding of domain concepts and relationships

3. **Conflict Resolution**: Flag for review
   - When AI scaffolding contradicts grounded evidence, surface the conflict
   - Present both perspectives to user for decision
   - Don't silently override either source

4. **Visualization**: PyVis interactive graph
   - Generate HTML visualizations using PyVis library
   - Social network-style interactive graph
   - Can be viewed in browser, shows relationships visually

5. **Cross-Project Concepts**: Hierarchical with project-specific salience
   - Global concept library exists (shared across projects)
   - Projects can extend/specialize global concepts
   - Salience weights are project-specific (same concept, different importance)
   - Allows knowledge reuse while maintaining project focus

---

## References

- Proof of concept script: `scratchpad/test_concept_map_sql.py`
- Existing insights system: `src/litrev_mcp/tools/insights.py`
- Existing RAG database: `src/litrev_mcp/tools/rag_db.py`
- Tool registration: `src/litrev_mcp/server.py`
