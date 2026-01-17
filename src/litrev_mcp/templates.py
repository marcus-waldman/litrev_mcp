"""Template constants for workflow best practices files."""

WORKFLOW_TEMPLATE = """# Literature Review Workflow

## Phase 1: Foundational Sources
**Goal**: Establish core concepts and cite authorities
**Status**: pending

**Completed**:
[]

**Next steps**:
- [ ] Identify core textbooks and methodological foundations
- [ ] Search for seminal papers in the field

---

## Phase 2: Domain-Specific Applications
**Goal**: Find precedents in your application area
**Status**: pending

**Completed**:
[]

**Next steps**:
- [ ] Search for bridge papers in related fields
- [ ] Identify gaps in target domain

---

## Phase 3: Novel Contributions
**Goal**: Confirm your contribution is unique
**Status**: pending

**Completed**:
[]

**Next steps**:
- [ ] Search for recent applications
- [ ] Document what makes your approach novel

---

## Session Logs

### Session {date}
Will be appended by save_session_log tool
"""

SYNTHESIS_NOTES_TEMPLATE = """# Synthesis Notes

## Current Understanding
*What we know right now - update as you learn*

## Key Sources
*Papers that matter and why*

- [ ] **Need**: [Description of gap]
- ✓ **Found**: [Citation] - [Why it matters]

## Gaps Still Open
*What you're looking for and haven't found*

- **Gap**: [Description]
  - Status: [searched/partially_found/not_found]
  - Why it matters: [Explanation]
  - Search strategy: [What you tried]

## How This Connects
*How insights map to manuscript sections*

**Section X.X**:
- Use [finding] from [source]
- Cite [author] for [concept]

## Pivots
*When understanding shifted - link to _pivots.md for details*
"""

GAPS_TEMPLATE = """# Gap Tracking

Track what you're searching for and haven't found yet.

## Format
```
### Gap: [Concise Description]
- **Status**: [searched/partially_found/not_found]
- **Why it matters**: [Explanation]
- **Search strategy**: [Queries tried]
- **Assigned to**: [Person or deferred]
- **Date opened**: YYYY-MM-DD
- **Last updated**: YYYY-MM-DD
```

---

## Open Gaps

"""

PIVOTS_TEMPLATE = """# Pivot Tracking

Document when understanding shifts significantly.

## Format
```
### Pivot: [Concise Description]
**Date**: YYYY-MM-DD

**What we thought before**: [Original assumption]

**What we learned**: [New understanding with evidence]

**Rationale for change**: [Why this matters]
- Source: [Citation or insight]
- Impact on manuscript: [How this changes argument]
- Citation strategy consequence**: [What changes]
```

---

## Pivots

"""

SEARCHES_TEMPLATE = """# Search Strategy Audit Trail

Record all searches for reproducibility.

## Format
```
### Search: [Goal/Gap Being Addressed]
**Date**: YYYY-MM-DD

**Query 1**: [Specific terms]
- Database: [PubMed/Semantic Scholar/ERIC]
- Result: [X papers found, Y relevant]

**Query 2**: [Refined query]
- Result: [Outcome]

**Conclusion**: [What you found or confirmed not finding]
```

---

## Searches

"""
