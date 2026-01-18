"""
Argument map tools for organizing literature knowledge.

Provides tools for managing a 3-level argument map that tracks:
- Topics: high-level organizational themes
- Propositions: arguable assertions (formerly 'concepts')
- Evidence: citable support from literature
- Relationships: argumentative and logical connections
- Gaps: salient propositions lacking evidence
"""

from typing import Optional
import re
import json
import os
from pathlib import Path

from litrev_mcp.config import config_manager
from litrev_mcp.tools import concept_map_db as db
from litrev_mcp.tools.rag_db import checkpoint

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


def _make_proposition_id(name: str) -> str:
    """Generate a concept ID from the concept name."""
    # Convert to lowercase, replace spaces/special chars with underscores
    proposition_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return proposition_id


def extract_concepts(
    project: str,
    insight_id: str,
    content: Optional[str] = None,
) -> dict:
    """
    Extract argument structure from an insight using Claude Opus.

    This tool automatically analyzes an insight and identifies:
    - Topics: high-level themes (e.g., "Measurement Error Problem")
    - Propositions: arguable assertions (e.g., "Measurement error causes attenuation bias")
    - Evidence: citable claims supporting propositions
    - Relationships: how propositions connect

    Args:
        project: Project code
        insight_id: The insight ID (filename without extension)
        content: Optional insight content (will read from file if not provided)

    Returns:
        Extracted topics, propositions, relationships, and evidence ready for add_propositions
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
    extraction_prompt = f"""You are extracting an argument structure from academic literature for a literature review.

INSIGHT CONTENT:
{content}

## Definitions

**Proposition**: An arguable assertion that makes a claim about how things relate.
- Format: "X causes/enables/requires Y" or "X is associated with Y"
- NOT a noun or thing (not "Attenuation Bias")
- YES a statement (e.g., "Measurement error causes attenuation bias")
- Represents your synthesized understanding

**Evidence**: A specific, citable claim that supports a proposition.
- Test: "Can you cite it?" If yes, it's evidence.
- Includes: author, year, and specific finding
- Example: "Effect estimates may be 20-70% smaller than true values (Keogh et al., 2020)"

**Topic**: A high-level theme that groups related propositions.
- Typically 3-8 per project
- Maps roughly to manuscript sections
- Example: "Measurement Error Problem", "Bayesian Estimation Requirements"

## Relationship Types

**Between Propositions** (use these):
- Argumentative: supports, contradicts, extends, qualifies, necessitates
- Logical: leads_to, precedes, enables, depends_on

**Between Topics** (suggest if obvious):
- motivates, contextualizes, contrasts_with, builds_on

## Instructions

1. Identify propositions (arguable assertions) from the source
2. For each proposition, extract supporting evidence (citable claims)
3. Suggest which topic(s) each proposition belongs to
4. Identify relationships between propositions
5. Use your judgment on granularity based on the source material
6. If evidence seems to conflict, note it in the evidence's contested_by field

Additionally, use your general knowledge to:
- Identify propositions that SHOULD exist but aren't explicitly mentioned (mark as source: "ai_knowledge")
- Add structural relationships from domain knowledge (mark as source: "ai_knowledge")

## Output Format

Return ONLY a JSON object:

{{
  "suggested_topics": [
    {{"name": "...", "description": "..."}}
  ],
  "propositions": [
    {{
      "name": "X causes Y",
      "definition": "Expanded explanation",
      "source": "insight",
      "suggested_topic": "Topic Name"
    }}
  ],
  "evidence": [
    {{
      "proposition_name": "X causes Y",
      "claim": "Specific finding (Author, Year)",
      "pages": "optional",
      "contested_by": "optional conflicting finding",
      "insight_id": "{insight_id}"
    }}
  ],
  "relationships": [
    {{
      "from": "Proposition A",
      "to": "Proposition B",
      "type": "leads_to",
      "source": "insight",
      "grounded_in": "{insight_id}"
    }}
  ]
}}

Be thorough but precise. Extract 5-15 propositions typically."""

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
            'topics_count': len(extracted.get('suggested_topics', [])),
            'propositions_count': len(extracted.get('propositions', [])),
            'relationships_count': len(extracted.get('relationships', [])),
            'evidence_count': len(extracted.get('evidence', [])),
            'message': f"Extracted {len(extracted.get('suggested_topics', []))} topics, "
                      f"{len(extracted.get('propositions', []))} propositions, "
                      f"{len(extracted.get('relationships', []))} relationships, "
                      f"{len(extracted.get('evidence', []))} evidence entries. "
                      "Review and use add_propositions to confirm."
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


def add_propositions(
    project: str,
    propositions: list[dict],
    topics: Optional[list[dict]] = None,
    relationships: Optional[list[dict]] = None,
    evidence: Optional[list[dict]] = None,
) -> dict:
    """
    Add propositions and topics to the argument map.

    Args:
        project: Project code
        propositions: List of proposition dicts with: name, definition, source, suggested_topic (optional)
        topics: List of topic dicts with: name, description
        relationships: List of relationship dicts with: from, to, type, source, grounded_in (optional)
        evidence: List of evidence dicts with: proposition_name, claim, insight_id, pages, contested_by (optional)

    Returns:
        Success status and summary of changes
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    added_topics = []
    added_propositions = []
    updated_propositions = []
    added_relationships = []
    added_evidence = []

    # Add topics first (so we can link propositions to them)
    topic_map = {}  # name -> topic_id
    if topics:
        for topic in topics:
            topic_name = topic['name']
            topic_id = _make_proposition_id(topic_name)  # Use same ID generation
            description = topic.get('description')

            # Upsert topic
            db.upsert_topic(topic_id, topic_name, description, project)
            topic_map[topic_name] = topic_id
            added_topics.append(topic_name)

    # Add propositions
    for prop in propositions:
        proposition_id = prop.get('id') or _make_proposition_id(prop['name'])
        name = prop['name']
        definition = prop.get('definition')
        source = prop['source']
        suggested_topic = prop.get('suggested_topic')

        # Upsert proposition
        is_new = not db.proposition_exists(proposition_id)
        db.upsert_proposition(proposition_id, name, definition, source)

        if is_new:
            added_propositions.append(name)
        else:
            updated_propositions.append(name)

        # Link to project (no salience - computed dynamically)
        db.link_proposition_to_project(project, proposition_id)

        # Link to topic if suggested
        if suggested_topic and suggested_topic in topic_map:
            db.link_proposition_to_topic(proposition_id, topic_map[suggested_topic], is_primary=True)

        # Add aliases if provided
        for alias in prop.get('aliases', []):
            db.add_alias(proposition_id, alias)

    # Add relationships
    if relationships:
        for rel in relationships:
            from_id = rel.get('from_id') or _make_proposition_id(rel['from'])
            to_id = rel.get('to_id') or _make_proposition_id(rel['to'])
            rel_type = rel['type']
            source = rel['source']
            grounded_in = rel.get('grounded_in')

            db.add_relationship(from_id, to_id, rel_type, source, grounded_in)
            added_relationships.append(f"{rel['from']} -{rel_type}-> {rel['to']}")

    # Add evidence
    if evidence:
        for ev in evidence:
            proposition_id = ev.get('proposition_id') or _make_proposition_id(ev.get('proposition_name', ''))
            claim = ev['claim']
            insight_id = ev['insight_id']
            pages = ev.get('pages')
            contested_by = ev.get('contested_by')

            db.add_evidence(proposition_id, project, insight_id, claim, pages, contested_by)
            added_evidence.append(f"{ev.get('proposition_name', proposition_id)}: {claim[:50]}...")

    # Force checkpoint to persist WAL to main database file
    checkpoint()

    return {
        'success': True,
        'project': project,
        'added_topics': added_topics,
        'added_propositions': added_propositions,
        'updated_propositions': updated_propositions,
        'added_relationships': added_relationships,
        'added_evidence': added_evidence,
        'message': f"Added {len(added_topics)} topics, {len(added_propositions)} new propositions, "
                   f"updated {len(updated_propositions)}, {len(added_relationships)} relationships, "
                   f"{len(added_evidence)} evidence entries"
    }


def create_topic(
    project: str,
    name: str,
    description: Optional[str] = None,
) -> dict:
    """
    Create a new topic for organizing propositions.

    Args:
        project: Project code
        name: Topic name (e.g., "Measurement Error Problem")
        description: Optional description

    Returns:
        Created topic details
    """
    db.init_concept_map_schema()

    topic_id = _make_proposition_id(name)
    topic = db.upsert_topic(topic_id, name, description, project)

    checkpoint()

    return {
        'success': True,
        'topic': topic,
        'message': f"Created topic: {name}"
    }


def list_topics(project: str) -> dict:
    """
    List all topics for a project.

    Args:
        project: Project code

    Returns:
        List of topics with proposition counts
    """
    db.init_concept_map_schema()

    topics = db.get_project_topics(project)

    return {
        'success': True,
        'project': project,
        'topics': topics,
        'count': len(topics),
        'message': f"Found {len(topics)} topics"
    }


def update_topic(
    project: str,
    topic_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> dict:
    """
    Update a topic's name or description.

    Args:
        project: Project code
        topic_id: Topic ID
        name: New name (optional)
        description: New description (optional)

    Returns:
        Updated topic details
    """
    db.init_concept_map_schema()

    # Get existing topic
    topic = db.get_topic(topic_id)
    if not topic:
        return {
            'success': False,
            'error': f"Topic not found: {topic_id}"
        }

    # Update with new values or keep existing
    new_name = name if name is not None else topic['name']
    new_desc = description if description is not None else topic['description']

    updated = db.upsert_topic(topic_id, new_name, new_desc, project)

    checkpoint()

    return {
        'success': True,
        'topic': updated,
        'message': f"Updated topic: {new_name}"
    }


def delete_topic(topic_id: str, confirm: bool = False) -> dict:
    """
    Delete a topic. Requires confirmation.

    Args:
        topic_id: Topic ID to delete
        confirm: Must be True to proceed

    Returns:
        Success status
    """
    if not confirm:
        return {
            'success': False,
            'error': 'Must set confirm=True to delete a topic. This will unlink all propositions from this topic.'
        }

    db.init_concept_map_schema()

    topic = db.get_topic(topic_id)
    if not topic:
        return {
            'success': False,
            'error': f"Topic not found: {topic_id}"
        }

    topic_name = topic['name']
    db.delete_topic(topic_id)

    checkpoint()

    return {
        'success': True,
        'message': f"Deleted topic: {topic_name}"
    }


def assign_proposition_topic(
    proposition_id: str,
    topic_id: str,
    is_primary: bool = False,
) -> dict:
    """
    Link a proposition to a topic.

    Args:
        proposition_id: Proposition ID
        topic_id: Topic ID
        is_primary: Whether this is the primary topic for the proposition

    Returns:
        Success status
    """
    db.init_concept_map_schema()

    db.link_proposition_to_topic(proposition_id, topic_id, is_primary)

    checkpoint()

    return {
        'success': True,
        'message': f"Linked proposition to topic (primary={is_primary})"
    }


def show_argument_map(
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
    stats = db.get_proposition_map_stats(project)

    # Get concepts
    concepts = db.get_project_propositions(project, filter_source=filter_source)

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
            relationships = db.get_relationships(proposition_id=concept['id'])
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


def update_proposition(
    project: str,
    proposition_id: str,
    updates: dict,
) -> dict:
    """
    Update a concept's attributes.

    Args:
        project: Project code
        proposition_id: The concept ID to update
        updates: Dict with optional keys: definition, salience_weight, add_alias,
                 add_relationship, add_evidence

    Returns:
        Success status and updated concept
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    # Check concept exists
    concept = db.get_proposition(proposition_id)
    if not concept:
        return {
            'success': False,
            'error': f"Concept '{proposition_id}' not found"
        }

    changes = []

    # Update definition
    if 'definition' in updates:
        db.upsert_proposition(
            proposition_id,
            concept['name'],
            updates['definition'],
            concept['source']
        )
        changes.append("Updated definition")

    # Update salience
    if 'salience_weight' in updates:
        db.update_proposition_salience(project, proposition_id, updates['salience_weight'])
        changes.append(f"Updated salience to {updates['salience_weight']}")

    # Add alias
    if 'add_alias' in updates:
        db.add_alias(proposition_id, updates['add_alias'])
        changes.append(f"Added alias: {updates['add_alias']}")

    # Add relationship
    if 'add_relationship' in updates:
        rel = updates['add_relationship']
        to_id = rel.get('target_id') or _make_proposition_id(rel['target'])
        db.add_relationship(
            proposition_id,
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
            proposition_id,
            project,
            ev['insight_id'],
            ev['claim'],
            ev.get('pages')
        )
        changes.append(f"Added evidence from {ev['insight_id']}")

    # Get updated concept
    updated_concept = db.get_proposition(proposition_id)

    return {
        'success': True,
        'proposition_id': proposition_id,
        'changes': changes,
        'concept': updated_concept
    }


def delete_proposition(
    project: str,
    proposition_id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete a concept from the project or globally.

    Args:
        project: Project code
        proposition_id: The concept ID to delete
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
    concept = db.get_proposition(proposition_id)
    if not concept:
        return {
            'success': False,
            'error': f"Concept '{proposition_id}' not found"
        }

    # Check if concept is used in other projects
    all_concepts = db.get_project_propositions(project)
    concept_in_project = any(c['id'] == proposition_id for c in all_concepts)

    if not concept_in_project:
        return {
            'success': False,
            'error': f"Concept '{proposition_id}' is not linked to project '{project}'"
        }

    # Remove from this project only (don't delete globally)
    db.unlink_concept_from_project(project, proposition_id)

    return {
        'success': True,
        'proposition_id': proposition_id,
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


def delete_relationship(
    project: str,
    from_concept: str,
    to_concept: str,
    relationship_type: str,
) -> dict:
    """
    Delete a specific relationship between concepts.

    Args:
        project: Project code (for verification)
        from_concept: Name of the source concept
        to_concept: Name of the target concept
        relationship_type: Type of relationship to delete

    Returns:
        Success status
    """
    # Initialize schema if needed
    db.init_concept_map_schema()

    from_id = _make_proposition_id(from_concept)
    to_id = _make_proposition_id(to_concept)

    # Verify concepts exist in project
    from_exists = db.proposition_exists(from_id)
    to_exists = db.proposition_exists(to_id)

    if not from_exists:
        return {
            'success': False,
            'error': f"Source concept '{from_concept}' not found"
        }

    if not to_exists:
        return {
            'success': False,
            'error': f"Target concept '{to_concept}' not found"
        }

    # Delete the relationship
    db.delete_relationship(from_id, to_id, relationship_type)

    # Force checkpoint
    checkpoint()

    return {
        'success': True,
        'from_concept': from_concept,
        'to_concept': to_concept,
        'relationship_type': relationship_type,
        'message': f"Deleted relationship: {from_concept} -{relationship_type}-> {to_concept}"
    }


def query_propositions(
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
    concepts = db.get_project_propositions(project)

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
            'proposition_id': concept['id'],
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


def find_argument_gaps(
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
            'proposition_id': gap['id'],
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


def visualize_argument_map(
    project: str,
    output_path: Optional[str] = None,
    filter_source: Optional[str] = None,
    highlight_gaps: bool = True,
    show_salience: bool = True,
) -> dict:
    """
    Generate interactive PyVis graph visualization of the argument map.

    Creates an HTML file with hierarchical interactive graph showing:
    - Topics as visual containers (grouped propositions)
    - Propositions as nodes (colored by evidence status)
    - Relationships as edges (within and across topics)
    - Click-to-expand evidence panels
    - Topic filter dropdown

    Colors:
    - Green: Grounded (from insights OR has 2+ evidence)
    - Yellow: Partial (1 evidence)
    - Red: Gaps (0 evidence)

    Args:
        project: Project code
        output_path: Optional custom output path (default: project/_argument_map.html)
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

    # Get topics for the project
    topics = db.get_project_topics(project)

    # Get all propositions for the project
    all_propositions = db.get_project_propositions(project, filter_source=filter_source)

    if not all_propositions:
        return {
            'success': False,
            'error': f"No propositions found for project {project}"
        }

    # Build proposition ID to topic mapping
    proposition_topics = {}  # proposition_id -> list of topic_ids
    for topic in topics:
        topic_props = db.get_topic_propositions(topic['id'])
        for prop in topic_props:
            if prop['proposition_id'] not in proposition_topics:
                proposition_topics[prop['proposition_id']] = []
            proposition_topics[prop['proposition_id']].append({
                'topic_id': topic['id'],
                'topic_name': topic['name'],
                'is_primary': prop['is_primary']
            })

    # Create network
    net = Network(
        height="800px",
        width="100%",
        bgcolor="#ffffff",
        font_color="black",
        directed=True
    )

    # Enable physics for layout
    net.barnes_hut()

    # Color schemes
    prop_colors = {
        'grounded': '#4CAF50',     # Green - insight OR 2+ evidence
        'partial': '#FFC107',      # Yellow - 1 evidence
        'gap': '#F44336',          # Red - 0 evidence
    }

    topic_colors = [
        '#E3F2FD',  # Light blue
        '#F3E5F5',  # Light purple
        '#E8F5E9',  # Light green
        '#FFF3E0',  # Light orange
        '#FCE4EC',  # Light pink
        '#F1F8E9',  # Light lime
        '#FFF9C4',  # Light yellow
        '#E0F2F1',  # Light teal
    ]

    # Build evidence data for JavaScript
    evidence_data = {}
    for prop in all_propositions:
        evidence_list = db.get_evidence(prop['id'], project)
        evidence_data[prop['id']] = [
            {
                'claim': ev['claim'],
                'insight_id': ev['insight_id'],
                'pages': ev['pages'] or 'N/A',
                'contested_by': ev.get('contested_by', None)
            }
            for ev in evidence_list
        ]

    # Add topic container nodes
    for i, topic in enumerate(topics):
        topic_color = topic_colors[i % len(topic_colors)]
        border_color = topic_color.replace('F', 'D').replace('E', 'C')  # Slightly darker

        net.add_node(
            f"topic_{topic['id']}",
            label=topic['name'],
            shape='box',
            color={'background': topic_color, 'border': border_color},
            size=50,
            font={'size': 20, 'bold': True},
            title=f"<b>Topic: {topic['name']}</b><br>{topic['description'] or ''}<br>{topic['proposition_count']} propositions",
            borderWidth=3,
            mass=5  # Heavier for stability
        )

    # Add proposition nodes
    for prop in all_propositions:
        # Determine color based on evidence
        evidence_count = prop['evidence_count']
        if prop['source'] == 'insight' or evidence_count >= 2:
            color = prop_colors['grounded']
            status = 'grounded'
        elif evidence_count == 1:
            color = prop_colors['partial']
            status = 'partial'
        else:
            color = prop_colors['gap'] if highlight_gaps else prop_colors['partial']
            status = 'gap'

        # Size by salience
        if show_salience:
            size = int(prop['salience'] * 30 + 10)
        else:
            size = 20

        # Determine group (primary topic if exists)
        group = None
        topic_names = []
        if prop['id'] in proposition_topics:
            for topic_info in proposition_topics[prop['id']]:
                topic_names.append(topic_info['topic_name'])
                if topic_info['is_primary']:
                    group = topic_info['topic_id']
            if group is None and proposition_topics[prop['id']]:
                # No primary, use first
                group = proposition_topics[prop['id']][0]['topic_id']

        # Build hover tooltip
        tooltip_lines = []
        tooltip_lines.append(f"<b>{prop['name']}</b>")
        tooltip_lines.append(f"<br>Status: {status}")
        tooltip_lines.append(f"<br>Salience: {prop['salience']:.2f}")
        if topic_names:
            tooltip_lines.append(f"<br>Topics: {', '.join(topic_names)}")

        if prop['definition']:
            tooltip_lines.append(f"<br><br>{prop['definition'][:200]}...")

        tooltip_lines.append(f"<br><br><i>Click for evidence details</i>")

        tooltip = "".join(tooltip_lines)

        # Add node with group assignment
        node_kwargs = {
            'label': prop['name'],
            'title': tooltip,
            'color': color,
            'size': size,
        }
        if group:
            node_kwargs['group'] = group

        net.add_node(prop['id'], **node_kwargs)

    # Get all relationships
    all_relationships = db.get_relationships()

    # Filter to relationships where both propositions are in this project
    prop_ids = {p['id'] for p in all_propositions}
    project_relationships = [
        r for r in all_relationships
        if r['from_concept_id'] in prop_ids and r['to_concept_id'] in prop_ids
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
            color=edge_color,
            smooth={'type': 'cubicBezier'}  # Curved for cross-topic visibility
        )

    # Set physics options with grouping
    net.set_options("""
    {
        "physics": {
            "barnesHut": {
                "gravitationalConstant": -10000,
                "centralGravity": 0.3,
                "springLength": 200,
                "springConstant": 0.04,
                "damping": 0.09,
                "avoidOverlap": 0.5
            },
            "minVelocity": 0.75,
            "stabilization": {
                "iterations": 150
            }
        },
        "groups": {
            "useDefaultGroups": true
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
        output_path = str(lit_path / project / "_argument_map.html")

    # Save the graph
    net.save_graph(output_path)

    # Read the generated HTML
    with open(output_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # Inject custom HTML/JS for evidence panel and topic filter
    import json
    evidence_json = json.dumps(evidence_data)
    topics_json = json.dumps([{'id': t['id'], 'name': t['name']} for t in topics])

    custom_html = f"""
    <style>
        #controls {{
            padding: 10px;
            background-color: #f5f5f5;
            border-bottom: 2px solid #ddd;
        }}
        #topic-filter {{
            padding: 5px 10px;
            font-size: 14px;
            margin-right: 10px;
        }}
        #evidence-panel {{
            position: fixed;
            right: 20px;
            top: 80px;
            width: 350px;
            max-height: 600px;
            overflow-y: auto;
            background: white;
            border: 2px solid #4CAF50;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            display: none;
            z-index: 1000;
        }}
        #evidence-panel h3 {{
            margin-top: 0;
            color: #4CAF50;
        }}
        #evidence-panel .close-btn {{
            float: right;
            cursor: pointer;
            font-size: 20px;
            color: #999;
        }}
        #evidence-panel .evidence-item {{
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #eee;
        }}
        #evidence-panel .contested {{
            color: #F44336;
            font-weight: bold;
        }}
        .legend {{
            display: inline-block;
            margin-left: 20px;
        }}
        .legend-item {{
            display: inline-block;
            margin-right: 15px;
        }}
        .legend-box {{
            display: inline-block;
            width: 15px;
            height: 15px;
            margin-right: 5px;
            border: 1px solid #333;
        }}
    </style>

    <div id="controls">
        <label for="topic-filter">Filter by topic:</label>
        <select id="topic-filter" onchange="filterByTopic(this.value)">
            <option value="all">All Topics</option>
        </select>

        <div class="legend">
            <div class="legend-item">
                <span class="legend-box" style="background-color: #4CAF50;"></span>
                <span>Grounded</span>
            </div>
            <div class="legend-item">
                <span class="legend-box" style="background-color: #FFC107;"></span>
                <span>Partial Evidence</span>
            </div>
            <div class="legend-item">
                <span class="legend-box" style="background-color: #F44336;"></span>
                <span>Gap</span>
            </div>
        </div>
    </div>

    <div id="evidence-panel">
        <span class="close-btn" onclick="closeEvidencePanel()">&times;</span>
        <h3 id="prop-name"></h3>
        <div id="evidence-list"></div>
    </div>

    <script type="text/javascript">
        var evidenceData = {evidence_json};
        var topicsData = {topics_json};

        // Populate topic filter
        var filterSelect = document.getElementById('topic-filter');
        topicsData.forEach(function(topic) {{
            var option = document.createElement('option');
            option.value = topic.id;
            option.text = topic.name;
            filterSelect.appendChild(option);
        }});

        // Handle node clicks
        network.on("click", function(params) {{
            if (params.nodes.length > 0) {{
                var nodeId = params.nodes[0];
                if (!nodeId.startsWith('topic_')) {{
                    showEvidencePanel(nodeId);
                }}
            }}
        }});

        function showEvidencePanel(propId) {{
            var panel = document.getElementById('evidence-panel');
            var propName = document.getElementById('prop-name');
            var evidenceList = document.getElementById('evidence-list');

            // Get proposition name from network
            var node = network.body.data.nodes.get(propId);
            propName.textContent = node.label;

            // Get evidence
            var evidence = evidenceData[propId] || [];

            if (evidence.length === 0) {{
                evidenceList.innerHTML = '<p><i>No evidence found</i></p>';
            }} else {{
                var html = '';
                evidence.forEach(function(ev, idx) {{
                    html += '<div class="evidence-item">';
                    html += '<p><strong>Evidence ' + (idx + 1) + ':</strong></p>';
                    html += '<p>' + ev.claim + '</p>';
                    html += '<p><small>Source: ' + ev.insight_id + ' (p. ' + ev.pages + ')</small></p>';
                    if (ev.contested_by) {{
                        html += '<p class="contested">⚠ Contested: ' + ev.contested_by + '</p>';
                    }}
                    html += '</div>';
                }});
                evidenceList.innerHTML = html;
            }}

            panel.style.display = 'block';
        }}

        function closeEvidencePanel() {{
            document.getElementById('evidence-panel').style.display = 'none';
        }}

        function filterByTopic(topicId) {{
            var nodes = network.body.data.nodes;
            var allNodes = nodes.get();

            if (topicId === 'all') {{
                // Show all proposition nodes
                allNodes.forEach(function(node) {{
                    if (!node.id.startsWith('topic_')) {{
                        nodes.update({{id: node.id, hidden: false}});
                    }}
                }});
            }} else {{
                // Hide all proposition nodes not in this topic
                allNodes.forEach(function(node) {{
                    if (!node.id.startsWith('topic_')) {{
                        var inTopic = node.group === topicId;
                        nodes.update({{id: node.id, hidden: !inTopic}});
                    }}
                }});
            }}
        }}
    </script>
    """

    # Insert custom HTML before closing body tag
    html_content = html_content.replace('</body>', custom_html + '</body>')

    # Write modified HTML back
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Get stats
    stats = db.get_proposition_map_stats(project)

    return {
        'success': True,
        'project': project,
        'output_path': output_path,
        'stats': stats,
        'topics_count': len(topics),
        'message': f"Interactive argument map saved to {output_path}. "
                  f"Open in browser to explore {len(topics)} topics, {stats['total_concepts']} propositions, "
                  f"and {stats['relationships']} relationships. "
                  f"Click propositions to see evidence details. Use topic filter to focus."
    }
