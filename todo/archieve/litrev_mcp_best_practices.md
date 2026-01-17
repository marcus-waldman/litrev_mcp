# litrev-mcp Best Practices Guide

A structured approach to literature reviews using litrev-mcp, designed to create auditable, narrative-driven synthesis rather than simple citation lists.

---

## Core Philosophy

Transform a literature review from a **list of references** into a **narrative of understanding**—showing how knowledge accumulated, what shifted, what remained unresolved, and what gaps exist.

---

## 1. Structured Multi-Phase Approach

Break your review into distinct phases with clear goals. Each phase targets specific gaps or angles.

### Phase Structure Template

```markdown
## Phase 1: Foundational Sources
**Goal**: Establish core concepts and cite authorities
**Status**: [pending/in_progress/complete]

**Completed**:
- ✓ Core textbooks identified
- ✓ Methodological foundations cited

**Next steps**:
- [ ] Search for historical context
- [ ] Identify seminal papers

---

## Phase 2: Domain-Specific Applications
**Goal**: Find precedents in your application area
**Status**: [pending/in_progress/complete]

**Completed**:
- ✓ Bridge papers in related fields found
- ✓ Gaps in target domain confirmed

**Next steps**:
- [ ] Search for emerging applications
```

### Why This Works
- Clear progress tracking
- Prevents overlapping searches
- Documents intentional scope boundaries
- Easier to delegate or hand off

---

## 2. Explicit Gap Documentation

Don't just record what you find—**document what you're still searching for**.

### Gap Tracking Template

```markdown
### Gaps Still Open

- **Gap**: CV-to-reliability conversion formulas
  - Status: [searched/partially found/not found]
  - Why it matters: Bridge biomarker literature to SEM framework
  - Search strategy: Try PubMed with "coefficient variation reliability ICC"
  - Assigned to: [person or deferred]

- **Gap**: LGCM applications to acute physiological responses
  - Status: Searched, all examples are longitudinal (months/years)
  - Implication: Our OGTT application may be novel
  - Next search: Growth curve + acute response + biomarker
```

### Why This Works
- Prevents duplicate searching
- Shows intentionality (why each gap matters)
- Makes it easy to see what still needs work
- Failed searches are valuable (confirm gaps)

---

## 3. Living Synthesis Document

Create a **synthesis-notes.md** as a narrative of understanding, not a bibliography.

### What Goes in synthesis-notes.md

**NOT**: Just a list of papers with citations
```markdown
- Aarsand et al. 2018 - EuBIVAS
- Ricos et al. 1999 - Biological variation database
- Carroll et al. 2006 - Measurement error
```

**YES**: Narrative with meaning and connections
```markdown
## CV Data: Biological Variation

### Current Understanding
**WE HAVE THE DATA!** Meta-analyzed CVs from EFLM database.

- Glucose: CVw=4.7%, CVg=8.0% → ICC≈0.74
- **Insulin: CVw=25.4%, CVg=33.5% → ICC≈0.64** ← OUR ANCHOR EXAMPLE
- HDL: CVw=5.7%, CVg=21.3% → ICC≈0.93

### Key Sources
- ✓ **EuBIVAS (2018-2021)** - Gold standard, meta-analyzed from 191 studies
- ✓ **Ricos 1999** - Historical context (now superseded by EuBIVAS)
- [ ] Still need: NEFA and triglycerides from EFLM or alternative source

### Gaps Still Open
- Inflammatory markers (IL-6, CRP) have very high CVw - may need separate section

### How This Connects
Insulin reliability of 0.64 is our compelling example—shows that single measurements have substantial error.
```

### Template Sections

```markdown
# [Topic Name]

## Current Understanding
*What we know right now*

## Key Sources
- ✓ [Citation] - [Why it matters]
- [ ] [Citation needed for] - [What you're looking for]

## Gaps Still Open
- [Unanswered questions]
- [Failed search attempts and why]

## How This Connects
*How this section serves your manuscript argument*
```

---

## 4. Insight Tagging Convention

When saving insights via `save_insight()`, use topic prefixes to create an audit trail.

### Tagging System

```
finding: [topic]        — Concrete fact or data point
connection: [topic]     — How something serves the argument
gap: [topic]           — Something not yet found
pivot: [topic]         — Thinking that changed
question: [topic]      — Unresolved issue needing clarification
```

### Example Usage

**Via CLI**:
```bash
litrev save_insight \
  --project MYPROJECT \
  --source consensus \
  --topic "finding: insulin CV from EuBIVAS" \
  --content "Insulin within-person CV = 25.4%, between = 33.5%, implies ICC ≈ 0.64"

litrev save_insight \
  --project MYPROJECT \
  --source reading_notes \
  --topic "pivot: EuBIVAS supersedes Ricos" \
  --content "EuBIVAS uses 191 meta-analyzed studies (2018-2021) vs Ricos 1999 single database. New gold standard for reliability estimates."

litrev save_insight \
  --project MYPROJECT \
  --source synthesis \
  --topic "gap: LGCM acute response trajectories" \
  --content "Searched extensively. All LGCM biomarker examples are longitudinal (months/years). No precedent for intensive repeated measures within single session. Confirms our OGTT application is novel."
```

### Why This Works
- Creates searchable audit trail
- Each insight tagged with type helps organize synthesis
- Pivots are explicitly tracked (what changed and why)
- Gaps are documented (prevents repeated searching)

---

## 5. Conceptual Pivot Tracking

When understanding shifts significantly, **document what changed and why**.

### Pivot Documentation Template

```markdown
## Pivot: [Concise Description]

**What we thought before**: [Original assumption]

**What we learned**: [New understanding with evidence]

**Rationale for change**: [Why this matters]
- Source: [Citation or search result]
- Impact on manuscript: [How this changes your argument]
- Citation strategy consequence: [Old source vs. new source]

**Example**:
## Pivot: EuBIVAS supersedes Ricos as primary source

**What we thought before**: Ricos 1999 is the canonical biological variation database

**What we learned**: EuBIVAS (2018-2021) is the current gold standard
- Meta-analyzed from 191 quality-assessed studies
- Modern analytical methods
- Higher quality criteria (BIVAC)

**Rationale for change**:
- Ricos is 25 years old (published 1999)
- EuBIVAS built directly on Ricos data but with modern standards
- Citing current data strengthens manuscript credibility

**Impact on citation strategy**:
- Primary citations: Aarsand et al. 2018, Carobene 2021 (EuBIVAS papers)
- Secondary (historical context): Ricos 1999 for "foundational work"
- Result: Manuscript appears current and evidence-based
```

---

## 6. Session Handoff Documentation

At the end of each session, create a **Session Log** entry in your synthesis-notes.md.

### Session Log Template

```markdown
### Session [Date]
**Status**: [ALL PHASES COMPLETE / Phase X in progress / Phase X blocked]

**Completed**:
- ✓ [Specific accomplishment with citations]
- ✓ [Data collected: what and how many]
- ✓ [Insights saved: count and types]

**Conceptual shifts documented**:
- **PIVOT**: [Topic] - [Brief description]
  - See insight: "pivot: [topic]" for details
  - Impact on citation hierarchy: [How this changes things]

**Active questions**:
- [Question for co-authors]
- [Unresolved search direction]
- [Interpretation you're uncertain about]

**Next steps**:
- [ ] [Specific search to run]
- [ ] [Decision needed from team]
- [ ] [Connection to make in manuscript]

**Blocked**: [What's stopping progress and why, if anything]
```

---

## 7. Connect to Downstream Work

Tie each insight explicitly to where it will be used in your manuscript.

### Connection Template

```markdown
## How This Connects

**Section 2.4 - CV and Reliability**:
- Use insulin CV data (25.4% within, 33.5% between) as anchor example
- Show ICC calculation: 33.5²/(33.5²+25.4²) = 0.64
- Cite EuBIVAS as source of meta-analyzed values

**Section 2.5 - Consequences for Inference**:
- Cite Keogh 2020 STRATOS guidance: "20-70% attenuation typical"
- Reference Brakenhoff 2018 for "triple whammy" concept
- Use Agier 2020 for concrete variable discovery numbers

**Section 6 - Limitations**:
- Cite Tomarken & Waller 2005 for general SEM limitations
- Van Erp 2017 for Bayesian prior sensitivity concerns
```

---

## 8. Iterative Depth

Don't accept first results—verify with multiple sources.

### Verification Checklist

- [ ] **Cross-check data** across multiple sources
  - Example: CV values in EFLM vs. Ricos vs. individual papers
  - Example: ICC interpretation across different domains

- [ ] **Use forward/backward snowball**
  - Backward: `semantic_scholar_references()` to find foundational work
  - Forward: `semantic_scholar_citations()` to find recent applications

- [ ] **Search multiple databases**
  - PubMed (biomedical domain)
  - Semantic Scholar (broad academic)
  - ERIC (education/educational measurement)

- [ ] **Verify contradictions**
  - If sources disagree, document why (methodology differences, population differences)
  - Example: Different CV values for same analyte → note source differences

---

## 9. Status Tracking in Zotero

Use Zotero paper statuses to track workflow progress.

### Zotero Status System

```
_needs-pdf              — Paper identified but PDF not yet acquired
_needs-notebooklm       — PDF acquired, needs detailed analysis/synthesis
_complete              — Paper fully analyzed and insights captured
```

### Workflow Commands

```bash
# See papers by status in your project
litrev zotero_get_by_status --project MYPROJECT --status needs_pdf

# Update status as you work
litrev zotero_update_status --title "Smith et al 2020 measurement error" --new_status complete

# Quick check: how much work remains?
litrev zotero_get_by_status --project MYPROJECT --status all
# Shows: X needs_pdf, Y needs_notebooklm, Z complete
```

---

## 10. Proactive Co-Author Questions

As gaps emerge, document questions for your team.

### Co-Author Questions Template

```markdown
## Questions for Co-Authors

### Data/Methods Questions
- [ ] Should we include [analyte]? We found CV data for [X] but not [Y].
- [ ] Our OGTT has [N] participants. Adequate for parallel process model with Bayesian estimation?
- [ ] Do you want to analyze [specific outcome]? Found [citation] supporting its importance.

### Interpretation Questions
- [ ] We found measurement error ranges from 0.64 (insulin) to 0.93 (HDL). Should we focus on high-error biomarkers?
- [ ] LGCM literature is all longitudinal (months/years). Our application to acute response (minutes) seems novel. Does this match your understanding?

### Citation/Scope Questions
- [ ] Should we cite [author] or is this outside our scope?
- [ ] Bayesian vs. frequentist SEM: Any preference for the empirical example?
```

---

## 11. Targeted vs. Broad Searches

Avoid massive keyword dumps; use specific, focused queries targeting particular gaps.

### Search Strategy Template

```markdown
## Search: [Gap Being Addressed]

**Goal**: [What question are we answering?]

**Query 1**: [Specific terms]
- Result: [Found X papers, Y relevant]
- Next query based on: [What you learned]

**Query 2**: [Refined based on Query 1]
- Result: [Outcome]

**Query 3**: [Alternative angle if queries 1-2 didn't yield what you need]
- Result: [Outcome]

**Conclusion**: [What you found or confirmed you're not finding]

**Example**:
## Search: CV-to-Reliability Conversion

**Goal**: Find papers that explicitly translate coefficient of variation to ICC/reliability

**Query 1**: "coefficient variation reliability ICC"
- Result: 2 relevant (Koo & Li 2016, Sandberg 2022)
- Issue: Mostly discussion of ICC calculation, not CV conversion

**Query 2**: "CV variance heteroscedastic log-transformation"
- Result: Found Pleil 2018 on biomarker error scaling
- Insight: Log transformation makes CV variance relationship linear

**Query 3**: "coefficient variation between-subject within-subject ICC formula"
- Result: Found that ICC = CVg²/(CVg²+CVw²) is standard approach
- Conclusion: This formula appears to be original synthesis work we need to derive ourselves

**Conclusion**: No single source explicitly bridges CV to ICC. Will need to derive and explain this ourselves in Section 2.4.
```

---

## 12. Data Organization

Create tables/matrices comparing sources and making patterns visible.

### Data Organization Examples

**CV Comparison Table** (in synthesis-notes.md):
```markdown
| Analyte | CVw (%) | CVg (%) | Source | Quality |
|---------|---------|---------|--------|---------|
| Glucose | 4.7 | 8.0 | EuBIVAS | Gold |
| Insulin | 25.4 | 33.5 | EuBIVAS | Gold |
| IL-6 | 48 | — | Cava 2000 | Silver |
| Cortisol | 29-57 | — | Danese 2024 | Gold |

**Notes**: EuBIVAS supersedes Ricos (2018 vs 1999). Cortisol diurnal variation confounds comparison.
```

**Attenuation Evidence** (for Section 2.5):
```markdown
## Measurement Error Consequences: Quantified Evidence

| Finding | Value | Source | Implication |
|---------|-------|--------|-------------|
| Typical attenuation | 20-70% | Keogh 2020 STRATOS | Correlations substantially reduced |
| Sensitivity to detect true predictors | 75% → 46% | Agier 2020 (exposome) | Lost 29 percentage points |
| False discovery proportion | 26% → 49% | Agier 2020 | Nearly doubled |
| Effect of correction | Roughly doubles estimates | Brakenhoff 2018 review | True effects recoverable |
| Large sample effect | No improvement in bias | Van Smeden 2019 | N doesn't solve this |
```

---

## Implementation Workflow

### Typical Session Flow

1. **Start with synthesis-notes.md**
   - Review "Gaps Still Open" and "Next steps" from previous session
   - Pick one gap to address

2. **Conduct targeted search**
   - Use 1-3 focused queries (not keyword dumps)
   - Document search strategy in synthesis-notes.md
   - Record what you found and what you're still looking for

3. **Add papers to Zotero**
   - `zotero_add_paper()` with project tag and source note
   - Papers auto-tagged with `_needs-pdf` status

4. **Extract insights**
   - As you read, use `save_insight()` with topic prefix
   - Link insights to specific manuscript sections
   - Document gaps and pivots

5. **Update synthesis-notes.md**
   - Move completed items from "Next steps" to "Completed"
   - Update gap status
   - Add new gaps discovered
   - Note any pivots to thinking

6. **End of session**
   - Create Session Log entry
   - List accomplishments, pivots, active questions
   - Document next steps
   - Update overall status (phase X complete/in progress)

---

## Quick Reference: Useful litrev-mcp Commands

```bash
# Add a paper quickly
litrev zotero_add_paper --project MYPROJECT --doi 10.1234/example --source "PubMed"

# Check status of papers
litrev zotero_get_by_status --project MYPROJECT --status needs_pdf

# Search your collected papers
litrev zotero_search --query "measurement error biomarkers" --project MYPROJECT

# Save an insight from reading
litrev save_insight \
  --project MYPROJECT \
  --source "reading_notes" \
  --topic "finding: insulin cv value" \
  --content "Insulin CVw=25.4% from EuBIVAS meta-analysis of 191 studies"

# Search insights to see what you've already captured
litrev search_insights --query "CV reliability translation" --project MYPROJECT

# Get your project dashboard
litrev project_status --project MYPROJECT
```

---

## Summary: The Audit Trail

By following these practices, your literature review creates:

✓ **Searchable insights** (tagged by type)
✓ **Documented reasoning** (why sources matter)
✓ **Gap tracking** (what you looked for and found/didn't find)
✓ **Pivot documentation** (what changed and why)
✓ **Session handoffs** (easy to resume work)
✓ **Downstream connections** (where each insight goes)
✓ **Data organization** (patterns visible at a glance)

This transforms the review from "a list of papers" into "a narrative of understanding"—auditable, reproducible, and directly usable for writing.

