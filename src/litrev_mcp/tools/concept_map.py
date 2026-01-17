"""
Concept map tools for organizing literature knowledge.

Provides tools for managing a concept map that tracks:
- Concepts from literature and AI general knowledge
- Relationships between concepts
- Salience (importance) weighted by purpose
- Gaps between salient concepts and grounded evidence
"""

from typing import Optional
import re
import json
import os
from pathlib import Path

from litrev_mcp.config import config_manager
from litrev_mcp.tools import concept_map_db as db

# Import Anthropic SDK for Opus
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Import OpenAI for embeddings
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Import PyVis for visualization
try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False


def _make_concept_id(name: str) -> str:
    """Generate a concept ID from the concept name."""
    # Convert to lowercase, replace spaces/special chars with underscores
    concept_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return concept_id


def extract_concepts(
    project: str,
    insight_id: str,
    content: Optional[str] = None,
) -> dict:
    """
    Extract concepts and relationships from an insight using Claude Opus.

    This tool automatically analyzes an insight and identifies:
    - Concepts mentioned with definitions
    - Relationships between concepts
    - Claims that serve as evidence

    Args:
        project: Project code
        insight_id: The insight ID (filename without extension)
        content: Optional insight content (will read from file if not provided)

    Returns:
        Extracted concepts, relationships, and evidence ready for add_concepts
    """
    if not ANTHROPIC_AVAILABLE:
        return {
            'success': False,
            'error': 'Anthropic SDK not installed. Run: pip install anthropic'
        }

    # Get API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {
            'success': False,
            'error': 'ANTHROPIC_API_KEY environment variable not set'
        }

    # Read insight content if not provided
    if content is None:
        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': 'Literature path not configured'
            }

        # Find the insight file
        notes_dir = lit_path / project / "_notes"
        insight_files = list(notes_dir.glob(f"*{insight_id}*.md"))

        if not insight_files:
            return {
                'success': False,
                'error': f"Insight file not found for ID: {insight_id}"
            }

        with open(insight_files[0], 'r', encoding='utf-8') as f:
            content = f.read()

    # Construct the extraction prompt
    extraction_prompt = f"""You are analyzing a literature review insight to extract concepts and their relationships.

INSIGHT CONTENT:
{content}

Your task is to extract:
1. **Concepts**: Key ideas, methods, phenomena, or constructs mentioned
2. **Relationships**: How concepts relate to each other (causes, corrects, requires, etc.)
3. **Evidence**: Specific claims that ground concepts in this literature

For each concept, provide:
- name: Clear, concise name
- definition: Brief definition (1-2 sentences)
- source: "insight" (since it comes from literature)

For each relationship, provide:
- from: Source concept name
- to: Target concept name
- type: One of (caused_by, corrected_by, type_of, requires, assumes, contradicts, related_to)
- source: "insight" (since it's grounded in literature)
- grounded_in: The insight_id ("{insight_id}")

For evidence, provide:
- concept_name: Which concept this evidences
- claim: The specific claim (keep it concise)
- insight_id: "{insight_id}"

Additionally, use your general knowledge to:
- Identify concepts that SHOULD exist but aren't explicitly mentioned (mark these as source: "ai_knowledge")
- Add structural relationships from domain knowledge (mark as source: "ai_knowledge")

Return ONLY a JSON object in this exact format:
{{
  "concepts": [
    {{"name": "...", "definition": "...", "source": "insight"}},
    {{"name": "...", "definition": "...", "source": "ai_knowledge"}}
  ],
  "relationships": [
    {{"from": "...", "to": "...", "type": "...", "source": "insight", "grounded_in": "{insight_id}"}},
    {{"from": "...", "to": "...", "type": "...", "source": "ai_knowledge"}}
  ],
  "evidence": [
    {{"concept_name": "...", "claim": "...", "insight_id": "{insight_id}"}}
  ]
}}

Be thorough but precise. Extract 5-15 concepts typically."""

    # Call Claude Opus
    try:
        client = anthropic.Anthropic(api_key=api_key)

        message = client.messages.create(
            model="claude-opus-4-20250514",  # Opus 4.5
            max_tokens=4096,
            messages=[
                {"role": "user", "content": extraction_prompt}
            ]
        )

        # Extract JSON from response
        response_text = message.content[0].text

        # Try to parse JSON from the response
        # Claude might wrap it in markdown code blocks
        if "```json" in response_text:
            json_start = response_text.index("```json") + 7
            json_end = response_text.index("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.index("```") + 3
            json_end = response_text.index("```", json_start)
            json_text = response_text[json_start:json_end].strip()
        else:
            json_text = response_text.strip()

        extracted = json.loads(json_text)

        return {
            'success': True,
            'project': project,
            'insight_id': insight_id,
            'extracted': extracted,
            'concepts_count': len(extracted.get('concepts', [])),
            'relationships_count': len(extracted.get('relationships', [])),
            'evidence_count': len(extracted.get('evidence', [])),
            'message': f"Extracted {len(extracted.get('concepts', []))} concepts, "
                      f"{len(extracted.get('relationships', []))} relationships, "
                      f"{len(extracted.get('evidence', []))} evidence entries. "
                      "Review and use add_concepts to confirm."
        }

    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f"Failed to parse JSON from Claude response: {e}",
            'raw_response': response_text if 'response_text' in locals() else None
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Error during extraction: {str(e)}"
        }


def add_concepts(
    project: str,
    concepts: list[dict],
    relationships: Optional[list[dict]] = None,
    evidence: Optional[list[dict]] = None,
) -> dict:
    """
    Add concepts to the concept map.

    Args:
        project: Project code
        concepts: List of concept dicts with: name, definition, source, salience_weight (optional)
        relationships: List of relationship dicts with: from, to, type, source, grounded_in (optional)
        evidence: List of evidence dicts with: concept_id, claim, insight_id, pages (optional)

    Returns:
        Success status and summary of changes
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    added_concepts = []
    updated_concepts = []
    added_relationships = []
    added_evidence = []

    # Add concepts
    for concept in concepts:
        concept_id = concept.get('id') or _make_concept_id(concept['name'])
        name = concept['name']
        definition = concept.get('definition')
        source = concept['source']
        salience_weight = concept.get('salience_weight', 0.5)

        # Upsert concept
        is_new = not db.concept_exists(concept_id)
        db.upsert_concept(concept_id, name, definition, source)

        if is_new:
            added_concepts.append(name)
        else:
            updated_concepts.append(name)

        # Link to project
        db.link_concept_to_project(project, concept_id, salience_weight)

        # Add aliases if provided
        for alias in concept.get('aliases', []):
            db.add_alias(concept_id, alias)

    # Add relationships
    if relationships:
        for rel in relationships:
            from_id = rel.get('from_id') or _make_concept_id(rel['from'])
            to_id = rel.get('to_id') or _make_concept_id(rel['to'])
            rel_type = rel['type']
            source = rel['source']
            grounded_in = rel.get('grounded_in')

            db.add_relationship(from_id, to_id, rel_type, source, grounded_in)
            added_relationships.append(f"{rel['from']} -{rel_type}-> {rel['to']}")

    # Add evidence
    if evidence:
        for ev in evidence:
            concept_id = ev.get('concept_id') or _make_concept_id(ev.get('concept_name', ''))
            claim = ev['claim']
            insight_id = ev['insight_id']
            pages = ev.get('pages')

            db.add_evidence(concept_id, project, insight_id, claim, pages)
            added_evidence.append(f"{ev.get('concept_name', concept_id)}: {claim[:50]}...")

    return {
        'success': True,
        'project': project,
        'added_concepts': added_concepts,
        'updated_concepts': updated_concepts,
        'added_relationships': added_relationships,
        'added_evidence': added_evidence,
        'message': f"Added {len(added_concepts)} new concepts, updated {len(updated_concepts)}, "
                   f"{len(added_relationships)} relationships, {len(added_evidence)} evidence entries"
    }


def show_concept_map(
    project: str,
    format: str = 'summary',
    filter_source: Optional[str] = None,
) -> dict:
    """
    Display the concept map for a project.

    Args:
        project: Project code
        format: 'summary' or 'detailed'
        filter_source: Optional filter ('insight', 'ai_knowledge', or None for all)

    Returns:
        Text representation of the concept map
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    # Get stats
    stats = db.get_concept_map_stats(project)

    # Get concepts
    concepts = db.get_project_concepts(project, filter_source=filter_source)

    # Build output
    output = []
    output.append(f"=== Concept Map: {project} ===\n")
    output.append(f"Total concepts: {stats['total_concepts']}")
    output.append(f"  Grounded (from insights): {stats['grounded']}")
    output.append(f"  AI scaffolding (with evidence): {stats['ai_scaffolding']}")
    output.append(f"  Gaps (AI knowledge, no evidence): {stats['gaps']}")
    output.append(f"Relationships: {stats['relationships']}\n")

    if format == 'detailed':
        output.append("\n--- Concepts ---\n")
        for concept in concepts:
            source_icon = "✓" if concept['source'] == 'insight' else "⚠"
            evidence_icon = f"[{concept['evidence_count']} evidence]" if concept['evidence_count'] > 0 else "[no evidence]"

            output.append(f"{source_icon} {concept['name']} (salience: {concept['salience']:.2f}) {evidence_icon}")
            if concept['definition']:
                output.append(f"    {concept['definition'][:100]}...")

            # Get relationships
            relationships = db.get_relationships(concept_id=concept['id'])
            if relationships:
                for rel in relationships:
                    if rel['from_concept_id'] == concept['id']:
                        output.append(f"    -> {rel['relationship_type']}: {rel['to_name']}")
                    else:
                        output.append(f"    <- {rel['relationship_type']}: {rel['from_name']}")

            # Get evidence
            if concept['evidence_count'] > 0:
                evidence_list = db.get_evidence(concept['id'], project)
                for ev in evidence_list[:3]:  # Show first 3
                    output.append(f"    Evidence [{ev['insight_id']}]: {ev['claim'][:80]}...")

            output.append("")

    return {
        'success': True,
        'project': project,
        'stats': stats,
        'text': "\n".join(output)
    }


def update_concept(
    project: str,
    concept_id: str,
    updates: dict,
) -> dict:
    """
    Update a concept's attributes.

    Args:
        project: Project code
        concept_id: The concept ID to update
        updates: Dict with optional keys: definition, salience_weight, add_alias,
                 add_relationship, add_evidence

    Returns:
        Success status and updated concept
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    # Check concept exists
    concept = db.get_concept(concept_id)
    if not concept:
        return {
            'success': False,
            'error': f"Concept '{concept_id}' not found"
        }

    changes = []

    # Update definition
    if 'definition' in updates:
        db.upsert_concept(
            concept_id,
            concept['name'],
            updates['definition'],
            concept['source']
        )
        changes.append("Updated definition")

    # Update salience
    if 'salience_weight' in updates:
        db.update_concept_salience(project, concept_id, updates['salience_weight'])
        changes.append(f"Updated salience to {updates['salience_weight']}")

    # Add alias
    if 'add_alias' in updates:
        db.add_alias(concept_id, updates['add_alias'])
        changes.append(f"Added alias: {updates['add_alias']}")

    # Add relationship
    if 'add_relationship' in updates:
        rel = updates['add_relationship']
        to_id = rel.get('target_id') or _make_concept_id(rel['target'])
        db.add_relationship(
            concept_id,
            to_id,
            rel['type'],
            rel.get('source', 'insight'),
            rel.get('grounded_in')
        )
        changes.append(f"Added relationship: {rel['type']} -> {rel['target']}")

    # Add evidence
    if 'add_evidence' in updates:
        ev = updates['add_evidence']
        db.add_evidence(
            concept_id,
            project,
            ev['insight_id'],
            ev['claim'],
            ev.get('pages')
        )
        changes.append(f"Added evidence from {ev['insight_id']}")

    # Get updated concept
    updated_concept = db.get_concept(concept_id)

    return {
        'success': True,
        'concept_id': concept_id,
        'changes': changes,
        'concept': updated_concept
    }


def delete_concept(
    project: str,
    concept_id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete a concept from the project or globally.

    Args:
        project: Project code
        concept_id: The concept ID to delete
        confirm: Must be True to proceed (safety check)

    Returns:
        Success status
    """
    if not confirm:
        return {
            'success': False,
            'error': "Must set confirm=True to delete a concept. This action cannot be undone."
        }

    # Initialize schema if needed
    db.init_concept_map_schema()

    # Check concept exists
    concept = db.get_concept(concept_id)
    if not concept:
        return {
            'success': False,
            'error': f"Concept '{concept_id}' not found"
        }

    # Check if concept is used in other projects
    all_concepts = db.get_project_concepts(project)
    concept_in_project = any(c['id'] == concept_id for c in all_concepts)

    if not concept_in_project:
        return {
            'success': False,
            'error': f"Concept '{concept_id}' is not linked to project '{project}'"
        }

    # Remove from this project only (don't delete globally)
    db.unlink_concept_from_project(project, concept_id)

    return {
        'success': True,
        'concept_id': concept_id,
        'message': f"Concept '{concept['name']}' removed from project {project}. "
                   "Global concept and relationships preserved."
    }


def list_conflicts(
    project: str,
    status: str = 'unresolved',
) -> dict:
    """
    List conflicts between AI knowledge and grounded evidence.

    Args:
        project: Project code
        status: Filter by status ('unresolved', 'all', etc.)

    Returns:
        List of conflicts
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    conflicts = db.get_conflicts(project, status)

    return {
        'success': True,
        'project': project,
        'status': status,
        'conflicts': conflicts,
        'count': len(conflicts)
    }


def resolve_conflict(
    conflict_id: int,
    resolution: str,
    note: Optional[str] = None,
) -> dict:
    """
    Resolve a conflict between AI knowledge and grounded evidence.

    Args:
        conflict_id: The conflict ID
        resolution: One of: 'ai_correct', 'evidence_correct', 'both_valid'
        note: Optional explanation

    Returns:
        Success status
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    valid_resolutions = ['ai_correct', 'evidence_correct', 'both_valid']
    if resolution not in valid_resolutions:
        return {
            'success': False,
            'error': f"Resolution must be one of: {', '.join(valid_resolutions)}"
        }

    db.resolve_conflict(conflict_id, resolution, note)

    return {
        'success': True,
        'conflict_id': conflict_id,
        'resolution': resolution,
        'message': f"Conflict {conflict_id} resolved as '{resolution}'"
    }


def query_concepts(
    project: str,
    query: str,
    purpose: Optional[str] = None,
    audience: Optional[str] = None,
    max_results: int = 10,
) -> dict:
    """
    Query the concept map with salience weighting.

    Uses hybrid approach:
    1. Embedding similarity for initial ranking
    2. Considers purpose/audience context for salience
    3. Returns concepts ordered by relevance

    Args:
        project: Project code
        query: Natural language query
        purpose: Context for salience weighting (e.g., "Methods section for journal")
        audience: Target audience (e.g., "Reviewers familiar with regression")
        max_results: Maximum results to return

    Returns:
        Concepts ranked by salience with evidence
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    # Get all concepts for project
    concepts = db.get_project_concepts(project)

    if not concepts:
        return {
            'success': True,
            'project': project,
            'query': query,
            'results': [],
            'message': "No concepts found in concept map for this project"
        }

    # Simple text matching for now (can be enhanced with embeddings later)
    # Score based on query match in name/definition
    scored_concepts = []
    query_lower = query.lower()

    for concept in concepts:
        score = concept['salience']  # Start with base salience

        # Boost if query matches name or definition
        if query_lower in concept['name'].lower():
            score += 0.3
        if concept['definition'] and query_lower in concept['definition'].lower():
            score += 0.2

        # Get evidence
        evidence_list = db.get_evidence(concept['id'], project)

        scored_concepts.append({
            'concept': concept['name'],
            'concept_id': concept['id'],
            'definition': concept['definition'],
            'salience': round(score, 3),
            'grounded': concept['source'] == 'insight' or concept['evidence_count'] > 0,
            'evidence': [
                f"{ev['claim']} [{ev['insight_id']}]"
                for ev in evidence_list[:3]
            ],
            'source': concept['source'],
        })

    # Sort by score
    scored_concepts.sort(key=lambda x: x['salience'], reverse=True)

    # Apply config threshold
    config = config_manager.config
    threshold = config.concept_map.salience_threshold
    filtered = [c for c in scored_concepts if c['salience'] >= threshold]

    return {
        'success': True,
        'project': project,
        'query': query,
        'purpose': purpose,
        'audience': audience,
        'results': filtered[:max_results],
        'total_matches': len(filtered),
        'message': f"Found {len(filtered)} relevant concepts (showing top {min(len(filtered), max_results)})"
    }


def find_concept_gaps(
    project: str,
    purpose: Optional[str] = None,
    audience: Optional[str] = None,
    min_salience: float = 0.5,
) -> dict:
    """
    Identify salient concepts that lack grounded evidence.

    Finds concepts that are:
    - Important for the purpose (high salience)
    - From AI knowledge without evidence (gaps)

    Args:
        project: Project code
        purpose: Context for salience (e.g., "Methods section")
        audience: Target audience
        min_salience: Minimum salience to consider (default 0.5)

    Returns:
        List of gaps with suggestions
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    # Get gaps from database
    gaps = db.find_gaps(project, min_salience)

    # Format results
    gap_list = []
    for gap in gaps:
        gap_list.append({
            'concept': gap['name'],
            'concept_id': gap['id'],
            'definition': gap['definition'],
            'salience': gap['salience'],
            'status': 'ai_scaffolding',
            'why_salient': f"Salience score: {gap['salience']:.2f}. Concept is related to your research but lacks grounded evidence.",
            'suggestion': f"Search for papers about '{gap['name']}' to ground this concept in literature."
        })

    return {
        'success': True,
        'project': project,
        'purpose': purpose,
        'audience': audience,
        'min_salience': min_salience,
        'gaps': gap_list,
        'count': len(gap_list),
        'message': f"Found {len(gap_list)} salient concepts without grounded evidence"
    }


def visualize_concept_map(
    project: str,
    output_path: Optional[str] = None,
    filter_source: Optional[str] = None,
    highlight_gaps: bool = True,
    show_salience: bool = True,
) -> dict:
    """
    Generate interactive PyVis graph visualization of the concept map.

    Creates an HTML file with interactive graph showing:
    - Nodes = concepts (color by source, size by salience)
    - Edges = relationships (labeled with type)
    - Tooltips with definitions and evidence

    Colors:
    - Green: Grounded (from insights with evidence)
    - Yellow/Amber: AI scaffolding (AI knowledge with some evidence)
    - Red: Gaps (AI knowledge without evidence)

    Args:
        project: Project code
        output_path: Optional custom output path (default: project/_concept_map.html)
        filter_source: Optional filter ('insight', 'ai_knowledge', or None for all)
        highlight_gaps: Whether to highlight gaps in red
        show_salience: Whether to size nodes by salience

    Returns:
        Success status and output path
    """
    if not PYVIS_AVAILABLE:
        return {
            'success': False,
            'error': 'PyVis not installed. Run: pip install pyvis'
        }

    # Initialize schema if needed
    db.init_concept_map_schema()

    # Get concepts and relationships
    concepts = db.get_project_concepts(project, filter_source=filter_source)

    if not concepts:
        return {
            'success': False,
            'error': f"No concepts found for project {project}"
        }

    # Create network
    net = Network(
        height="750px",
        width="100%",
        bgcolor="#ffffff",
        font_color="black",
        directed=True
    )

    # Enable physics for layout
    net.barnes_hut()

    # Color scheme
    colors = {
        'grounded': '#4CAF50',      # Green - has evidence
        'ai_scaffolding': '#FFC107',  # Yellow/amber - AI with some evidence
        'gap': '#F44336',            # Red - AI without evidence
    }

    # Add nodes
    for concept in concepts:
        # Determine color
        if concept['source'] == 'insight':
            color = colors['grounded']
            status = 'grounded'
        elif concept['evidence_count'] > 0:
            color = colors['ai_scaffolding']
            status = 'ai_scaffolding'
        else:
            color = colors['gap'] if highlight_gaps else colors['ai_scaffolding']
            status = 'gap'

        # Size by salience
        if show_salience:
            size = int(concept['salience'] * 30 + 10)
        else:
            size = 20

        # Build tooltip
        tooltip_lines = []
        tooltip_lines.append(f"<b>{concept['name']}</b>")
        tooltip_lines.append(f"<br>Status: {status}")
        tooltip_lines.append(f"<br>Salience: {concept['salience']:.2f}")

        if concept['definition']:
            tooltip_lines.append(f"<br><br>{concept['definition'][:200]}...")

        if concept['evidence_count'] > 0:
            evidence_list = db.get_evidence(concept['id'], project)
            tooltip_lines.append(f"<br><br><b>Evidence ({concept['evidence_count']}):</b>")
            for ev in evidence_list[:3]:
                tooltip_lines.append(f"<br>• {ev['claim'][:100]}... [{ev['insight_id']}]")

        tooltip = "".join(tooltip_lines)

        # Add node
        net.add_node(
            concept['id'],
            label=concept['name'],
            title=tooltip,
            color=color,
            size=size
        )

    # Get all relationships for concepts in this project
    all_relationships = db.get_relationships()

    # Filter to relationships where both concepts are in this project
    concept_ids = {c['id'] for c in concepts}
    project_relationships = [
        r for r in all_relationships
        if r['from_concept_id'] in concept_ids and r['to_concept_id'] in concept_ids
    ]

    # Add edges
    for rel in project_relationships:
        # Edge tooltip
        tooltip = f"{rel['relationship_type']}"
        if rel['grounded_in']:
            tooltip += f" (grounded in {rel['grounded_in']})"

        # Edge color based on source
        edge_color = '#4CAF50' if rel['source'] == 'insight' else '#9E9E9E'

        net.add_edge(
            rel['from_concept_id'],
            rel['to_concept_id'],
            title=tooltip,
            label=rel['relationship_type'],
            color=edge_color
        )

    # Set physics options
    net.set_options("""
    {
        "physics": {
            "barnesHut": {
                "gravitationalConstant": -8000,
                "springLength": 150,
                "springConstant": 0.04
            },
            "minVelocity": 0.75
        }
    }
    """)

    # Determine output path
    if output_path is None:
        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': 'Literature path not configured'
            }
        output_path = str(lit_path / project / "_concept_map.html")

    # Save the graph
    net.save_graph(output_path)

    # Get stats
    stats = db.get_concept_map_stats(project)

    return {
        'success': True,
        'project': project,
        'output_path': output_path,
        'stats': stats,
        'message': f"Interactive concept map saved to {output_path}. "
                  f"Open in browser to explore {stats['total_concepts']} concepts "
                  f"and {stats['relationships']} relationships."
    }
