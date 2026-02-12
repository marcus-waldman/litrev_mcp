"""
Argument map tools for organizing literature knowledge.

Provides tools for managing an argument map that tracks:
- Topics: high-level organizational themes
- Propositions: arguable assertions (formerly 'concepts')
- Evidence: citable support from literature
- Relationships: argumentative and logical connections
- Gaps: ungrounded AI scaffolding propositions lacking evidence
"""

from typing import Optional
import re
import json
import os
from pathlib import Path

from litrev_mcp.config import config_manager
from litrev_mcp.tools import argument_map_db as db
from litrev_mcp.tools.rag_db import checkpoint
from litrev_mcp.tools.raw_http import async_anthropic_messages_raw

# Import PyVis for visualization
try:
    from pyvis.network import Network
    PYVIS_AVAILABLE = True
except ImportError:
    PYVIS_AVAILABLE = False


def _make_proposition_id(name: str) -> str:
    """Generate a proposition ID from the proposition name."""
    # Convert to lowercase, replace spaces/special chars with underscores
    proposition_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return proposition_id


async def extract_concepts(
    project: str,
    insight_id: str,
    content: Optional[str] = None,
    extracted_data: Optional[dict] = None,
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
        extracted_data: Optional pre-extracted data dict (skip API call).
            Keys: suggested_topics, propositions, evidence, relationships

    Returns:
        Extracted topics, propositions, relationships, and evidence ready for add_propositions
    """
    # If pre-extracted data is provided, skip the API call entirely
    if extracted_data is not None:
        extracted = extracted_data
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

    # Call Claude Opus via raw HTTP (avoids httpx deadlock in MCP event loop)
    try:
        response_text = await async_anthropic_messages_raw(
            model="claude-opus-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": extraction_prompt}],
            api_key=api_key,
        )

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
    db.init_argument_map_schema()

    added_topics = []
    added_propositions = []
    updated_propositions = []
    added_relationships = []
    added_evidence = []

    # Build topic_map from existing topics (so suggested_topic works for pre-existing topics)
    existing_topics = db.get_project_topics(project)
    topic_map = {t['name']: t['id'] for t in existing_topics}

    # Add new topics (and update topic_map)
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

        # Link to project
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
    db.init_argument_map_schema()

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
    db.init_argument_map_schema()

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
    db.init_argument_map_schema()

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

    db.init_argument_map_schema()

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
    db.init_argument_map_schema()

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
    Display the argument map for a project.

    Args:
        project: Project code
        format: 'summary' or 'detailed'
        filter_source: Optional filter ('insight', 'ai_knowledge', or None for all)

    Returns:
        Text representation of the argument map
    """
    # Initialize schema if needed
    db.init_argument_map_schema()

    # Get stats
    stats = db.get_argument_map_stats(project)

    # Get propositions
    propositions = db.get_project_propositions(project, filter_source=filter_source)

    # Build output
    output = []
    output.append(f"=== Argument Map: {project} ===\n")
    output.append(f"Total propositions: {stats['total_propositions']}")
    output.append(f"  Grounded (from insights): {stats['grounded']}")
    output.append(f"  AI scaffolding (with evidence): {stats['ai_scaffolding']}")
    output.append(f"  Gaps (AI knowledge, no evidence): {stats['gaps']}")
    output.append(f"Relationships: {stats['relationships']}\n")

    if format == 'detailed':
        output.append("\n--- Propositions ---\n")
        for proposition in propositions:
            source_icon = "✓" if proposition['source'] == 'insight' else "⚠"
            evidence_icon = f"[{proposition['evidence_count']} evidence]" if proposition['evidence_count'] > 0 else "[no evidence]"

            output.append(f"{source_icon} {proposition['name']} {evidence_icon}")
            if proposition['definition']:
                output.append(f"    {proposition['definition'][:100]}...")

            # Get relationships
            relationships = db.get_relationships(proposition_id=proposition['id'])
            if relationships:
                for rel in relationships:
                    if rel['from_proposition_id'] == proposition['id']:
                        output.append(f"    -> {rel['relationship_type']}: {rel['to_name']}")
                    else:
                        output.append(f"    <- {rel['relationship_type']}: {rel['from_name']}")

            # Get evidence
            if proposition['evidence_count'] > 0:
                evidence_list = db.get_evidence(proposition['id'], project)
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
    Update a proposition's attributes.

    Args:
        project: Project code
        proposition_id: The proposition ID to update
        updates: Dict with optional keys: definition, add_alias,
                 add_relationship, add_evidence

    Returns:
        Success status and updated proposition
    """
    # Initialize schema if needed
    db.init_argument_map_schema()

    # Check proposition exists
    proposition = db.get_proposition(proposition_id)
    if not proposition:
        return {
            'success': False,
            'error': f"Proposition '{proposition_id}' not found"
        }

    changes = []

    # Update definition
    if 'definition' in updates:
        db.upsert_proposition(
            proposition_id,
            proposition['name'],
            updates['definition'],
            proposition['source']
        )
        changes.append("Updated definition")

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

    # Get updated proposition
    updated_proposition = db.get_proposition(proposition_id)

    return {
        'success': True,
        'proposition_id': proposition_id,
        'changes': changes,
        'proposition': updated_proposition
    }


def delete_proposition(
    project: str,
    proposition_id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete a proposition from the project or globally.

    Args:
        project: Project code
        proposition_id: The proposition ID to delete
        confirm: Must be True to proceed (safety check)

    Returns:
        Success status
    """
    if not confirm:
        return {
            'success': False,
            'error': "Must set confirm=True to delete a proposition. This action cannot be undone."
        }

    # Initialize schema if needed
    db.init_argument_map_schema()

    # Check proposition exists
    proposition = db.get_proposition(proposition_id)
    if not proposition:
        return {
            'success': False,
            'error': f"Proposition '{proposition_id}' not found"
        }

    # Check if proposition is used in this project
    all_propositions = db.get_project_propositions(project)
    prop_in_project = any(c['id'] == proposition_id for c in all_propositions)

    if not prop_in_project:
        return {
            'success': False,
            'error': f"Proposition '{proposition_id}' is not linked to project '{project}'"
        }

    # Remove from this project only (don't delete globally)
    db.unlink_proposition_from_project(project, proposition_id)

    return {
        'success': True,
        'proposition_id': proposition_id,
        'message': f"Proposition '{proposition['name']}' removed from project {project}. "
                   "Global proposition and relationships preserved."
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
    db.init_argument_map_schema()

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
    db.init_argument_map_schema()

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
    from_proposition: str,
    to_proposition: str,
    relationship_type: str,
) -> dict:
    """
    Delete a specific relationship between propositions.

    Args:
        project: Project code (for verification)
        from_proposition: Name of the source proposition
        to_proposition: Name of the target proposition
        relationship_type: Type of relationship to delete

    Returns:
        Success status
    """
    # Initialize schema if needed
    db.init_argument_map_schema()

    from_id = _make_proposition_id(from_proposition)
    to_id = _make_proposition_id(to_proposition)

    # Verify concepts exist in project
    from_exists = db.proposition_exists(from_id)
    to_exists = db.proposition_exists(to_id)

    if not from_exists:
        return {
            'success': False,
            'error': f"Source proposition '{from_proposition}' not found"
        }

    if not to_exists:
        return {
            'success': False,
            'error': f"Target proposition '{to_proposition}' not found"
        }

    # Delete the relationship
    db.delete_relationship(from_id, to_id, relationship_type)

    # Force checkpoint
    checkpoint()

    return {
        'success': True,
        'from_proposition': from_proposition,
        'to_proposition': to_proposition,
        'relationship_type': relationship_type,
        'message': f"Deleted relationship: {from_proposition} -{relationship_type}-> {to_proposition}"
    }


def query_propositions(
    project: str,
    query: str,
    max_results: int = 10,
) -> dict:
    """
    Search the argument map by keyword. Returns propositions matching the query,
    ranked by relevance. For semantic search, use search_argument_map instead.

    Args:
        project: Project code
        query: Keyword query to match against proposition names and definitions
        max_results: Maximum results to return

    Returns:
        Propositions ranked by relevance with evidence
    """
    # Initialize schema if needed
    db.init_argument_map_schema()

    # Get all propositions for project
    propositions = db.get_project_propositions(project)

    if not propositions:
        return {
            'success': True,
            'project': project,
            'query': query,
            'results': [],
            'message': "No propositions found in argument map for this project"
        }

    # Simple text matching (for semantic search, use search_argument_map)
    scored_propositions = []
    query_lower = query.lower()

    for proposition in propositions:
        # Base score: higher for grounded propositions
        score = 0.5 if proposition['source'] == 'insight' or proposition['evidence_count'] > 0 else 0.3

        # Boost if query matches name or definition
        if query_lower in proposition['name'].lower():
            score += 0.3
        if proposition['definition'] and query_lower in proposition['definition'].lower():
            score += 0.2

        # Skip if no match at all
        if score <= 0.5 and proposition['source'] != 'insight' and proposition['evidence_count'] == 0:
            if query_lower not in proposition['name'].lower() and (not proposition['definition'] or query_lower not in proposition['definition'].lower()):
                continue

        # Get evidence
        evidence_list = db.get_evidence(proposition['id'], project)

        scored_propositions.append({
            'proposition': proposition['name'],
            'proposition_id': proposition['id'],
            'definition': proposition['definition'],
            'relevance': round(score, 3),
            'grounded': proposition['source'] == 'insight' or proposition['evidence_count'] > 0,
            'evidence': [
                f"{ev['claim']} [{ev['insight_id']}]"
                for ev in evidence_list[:3]
            ],
            'source': proposition['source'],
        })

    # Sort by score
    scored_propositions.sort(key=lambda x: x['relevance'], reverse=True)

    return {
        'success': True,
        'project': project,
        'query': query,
        'results': scored_propositions[:max_results],
        'total_matches': len(scored_propositions),
        'message': f"Found {len(scored_propositions)} matching propositions (showing top {min(len(scored_propositions), max_results)}). For semantic search, use search_argument_map."
    }


def find_argument_gaps(
    project: str,
) -> dict:
    """
    Find AI scaffolding propositions that lack grounded evidence from your literature.

    Returns propositions sourced from AI general knowledge that have no
    supporting evidence from your papers. These are candidates for literature
    searches to ground them, or for removal if not relevant.

    Args:
        project: Project code

    Returns:
        List of ungrounded propositions with suggestions
    """
    # Initialize schema if needed
    db.init_argument_map_schema()

    # Get gaps from database
    gaps = db.find_gaps(project)

    # Format results
    gap_list = []
    for gap in gaps:
        gap_list.append({
            'proposition': gap['name'],
            'proposition_id': gap['id'],
            'definition': gap['definition'],
            'status': 'ungrounded',
            'reason': "AI scaffolding proposition without evidence from your literature.",
            'suggestion': f"Search for papers about '{gap['name']}' to ground this proposition in literature."
        })

    return {
        'success': True,
        'project': project,
        'gaps': gap_list,
        'count': len(gap_list),
        'message': f"Found {len(gap_list)} ungrounded AI scaffolding propositions"
    }


def visualize_argument_map(
    project: str,
    output_path: Optional[str] = None,
    filter_source: Optional[str] = None,
    highlight_gaps: bool = True,
) -> dict:
    """
    Generate interactive PyVis graph visualization of the argument map.

    Creates an HTML file with hierarchical interactive graph showing:
    - Topics as visual containers (grouped propositions)
    - Propositions as nodes (colored by evidence status, sized by evidence count)
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

    Returns:
        Success status and output path
    """
    if not PYVIS_AVAILABLE:
        return {
            'success': False,
            'error': 'PyVis not installed. Run: pip install pyvis'
        }

    # Initialize schema if needed
    db.init_argument_map_schema()

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

        # Size by evidence count: 0 evidence = 10, 1 = 20, 2 = 30, 3+ = 40
        size = min(evidence_count * 10 + 10, 40)

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
        tooltip_lines.append(f"<br>Evidence: {evidence_count}")
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
        if r['from_proposition_id'] in prop_ids and r['to_proposition_id'] in prop_ids
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
            rel['from_proposition_id'],
            rel['to_proposition_id'],
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

    # Load issues for this project
    issues_data = _load_issues(project)
    open_issues = [i for i in issues_data['issues'] if i['status'] == 'open']

    # Build issue lookup by proposition_id
    issues_by_prop = {}
    for issue in open_issues:
        prop_id = issue['proposition_id']
        if prop_id not in issues_by_prop:
            issues_by_prop[prop_id] = []
        issues_by_prop[prop_id].append(issue)

    # Inject custom HTML/JS for evidence panel, topic filter, and issue tracking
    evidence_json = json.dumps(evidence_data)
    topics_json = json.dumps([{'id': t['id'], 'name': t['name']} for t in topics])
    issues_json = json.dumps(issues_data['issues'])
    issues_by_prop_json = json.dumps(issues_by_prop)
    issue_types_json = json.dumps(ISSUE_TYPES)

    # Get issues file path for browser
    issues_path = _get_issues_path(project)
    issues_filename = issues_path.name if issues_path else '_issues.json'

    # custom_html now only contains styles and scripts (HTML structure is in new_body)
    custom_html = f"""
    <style>
        body {{
            margin: 0;
            overflow: hidden;
        }}
        #app-container {{
            display: flex;
            height: 100vh;
            width: 100vw;
        }}
        #issues-panel {{
            width: 280px;
            min-width: 280px;
            background: #fafafa;
            border-right: 2px solid #ddd;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        #issues-header {{
            padding: 15px;
            background: #f5f5f5;
            border-bottom: 1px solid #ddd;
        }}
        #issues-header h3 {{
            margin: 0 0 10px 0;
            color: #333;
            font-size: 16px;
        }}
        #issue-status-filter {{
            width: 100%;
            padding: 5px;
            font-size: 13px;
        }}
        #issues-list {{
            flex: 1;
            overflow-y: auto;
            padding: 10px;
        }}
        .issue-card {{
            background: white;
            border: 1px solid #ddd;
            border-left: 4px solid #F44336;
            border-radius: 4px;
            padding: 10px;
            margin-bottom: 10px;
            cursor: pointer;
            font-size: 13px;
        }}
        .issue-card:hover {{
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .issue-card.resolved {{
            border-left-color: #4CAF50;
            opacity: 0.7;
        }}
        .issue-card .issue-type {{
            display: inline-block;
            background: #e0e0e0;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 11px;
            text-transform: uppercase;
            margin-bottom: 5px;
        }}
        .issue-card .issue-type.needs_evidence {{ background: #FFCDD2; }}
        .issue-card .issue-type.rephrase {{ background: #FFF9C4; }}
        .issue-card .issue-type.wrong_topic {{ background: #E1BEE7; }}
        .issue-card .issue-type.merge {{ background: #BBDEFB; }}
        .issue-card .issue-type.split {{ background: #C8E6C9; }}
        .issue-card .issue-type.delete {{ background: #FFCCBC; }}
        .issue-card .issue-prop {{
            font-weight: bold;
            color: #333;
            margin-bottom: 5px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        .issue-card .issue-desc {{
            color: #666;
            font-size: 12px;
        }}
        #add-issue-btn {{
            margin: 10px;
            padding: 10px;
            background: #2196F3;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}
        #add-issue-btn:hover {{
            background: #1976D2;
        }}
        #main-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        #controls {{
            padding: 10px 15px;
            background-color: #f5f5f5;
            border-bottom: 2px solid #ddd;
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 10px;
        }}
        #topic-filter {{
            padding: 5px 10px;
            font-size: 14px;
        }}
        #graph-container {{
            flex: 1;
            position: relative;
            overflow: hidden;
        }}
        #graph-container .card {{
            width: 100% !important;
            height: 100% !important;
            margin: 0 !important;
            border: none !important;
        }}
        #mynetwork {{
            width: 100% !important;
            height: 100% !important;
            border: none !important;
        }}
        #evidence-panel {{
            position: fixed;
            right: 20px;
            top: 80px;
            width: 350px;
            max-height: calc(100vh - 120px);
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
            padding-right: 30px;
        }}
        #evidence-panel .close-btn {{
            position: absolute;
            right: 15px;
            top: 10px;
            cursor: pointer;
            font-size: 24px;
            color: #999;
            line-height: 1;
        }}
        #evidence-panel .close-btn:hover {{
            color: #333;
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
        #evidence-panel .prop-issues {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 2px solid #eee;
        }}
        #evidence-panel .prop-issues h4 {{
            margin: 0 0 10px 0;
            color: #F44336;
        }}
        #add-issue-to-prop-btn {{
            margin-top: 15px;
            padding: 8px 16px;
            background: #FF9800;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 13px;
        }}
        #add-issue-to-prop-btn:hover {{
            background: #F57C00;
        }}
        .legend {{
            display: flex;
            gap: 15px;
            margin-left: auto;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            font-size: 13px;
        }}
        .legend-box {{
            width: 15px;
            height: 15px;
            border: 1px solid #333;
        }}
        /* Modal styles */
        .modal-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 2000;
        }}
        .modal-overlay.active {{
            display: flex;
        }}
        .modal {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            width: 450px;
            max-width: 90vw;
            max-height: 80vh;
            overflow-y: auto;
        }}
        .modal h3 {{
            margin-top: 0;
            color: #333;
        }}
        .modal label {{
            display: block;
            margin-bottom: 5px;
            font-weight: bold;
            color: #555;
        }}
        .modal select, .modal textarea {{
            width: 100%;
            padding: 8px;
            margin-bottom: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            box-sizing: border-box;
        }}
        .modal textarea {{
            min-height: 100px;
            resize: vertical;
        }}
        .modal-buttons {{
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            margin-top: 15px;
        }}
        .modal-buttons button {{
            padding: 8px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}
        .btn-cancel {{
            background: #e0e0e0;
            color: #333;
        }}
        .btn-cancel:hover {{
            background: #d0d0d0;
        }}
        .btn-submit {{
            background: #4CAF50;
            color: white;
        }}
        .btn-submit:hover {{
            background: #43A047;
        }}
        .btn-danger {{
            background: #F44336;
            color: white;
        }}
        .btn-danger:hover {{
            background: #E53935;
        }}
        #file-status {{
            padding: 5px 10px;
            font-size: 12px;
            background: #fff3e0;
            border: 1px solid #FFB74D;
            border-radius: 4px;
            display: none;
        }}
        #file-status.connected {{
            background: #E8F5E9;
            border-color: #81C784;
        }}
    </style>

    <script type="text/javascript">
        // Data from Python
        var evidenceData = {evidence_json};
        var topicsData = {topics_json};
        var issuesData = {issues_json};
        var issuesByProp = {issues_by_prop_json};
        var issueTypes = {issue_types_json};
        var projectCode = "{project}";
        var issuesFilename = "{issues_filename}";

        // File handle for persistence
        var fileHandle = null;

        // Initialize after network is ready
        document.addEventListener('DOMContentLoaded', function() {{
            // Wait for network to be available
            var checkNetwork = setInterval(function() {{
                if (typeof network !== 'undefined') {{
                    clearInterval(checkNetwork);
                    initializeUI();
                    updateNodeBorders();
                }}
            }}, 100);
        }});

        function initializeUI() {{
            // Populate topic filter
            var filterSelect = document.getElementById('topic-filter');
            topicsData.forEach(function(topic) {{
                var option = document.createElement('option');
                option.value = topic.id;
                option.text = topic.name;
                filterSelect.appendChild(option);
            }});

            // Populate proposition select in add issue modal
            var propSelect = document.getElementById('issue-prop-select');
            var nodes = network.body.data.nodes.get();
            nodes.forEach(function(node) {{
                if (!node.id.startsWith('topic_')) {{
                    var option = document.createElement('option');
                    option.value = node.id;
                    option.text = node.label;
                    propSelect.appendChild(option);
                }}
            }});

            // Populate issue type select
            var typeSelect = document.getElementById('issue-type-select');
            issueTypes.forEach(function(t) {{
                var option = document.createElement('option');
                option.value = t;
                option.text = t.replace(/_/g, ' ');
                typeSelect.appendChild(option);
            }});

            // Render issues list
            renderIssuesList('open');

            // Setup click handler
            network.on("click", function(params) {{
                if (params.nodes.length > 0) {{
                    var nodeId = params.nodes[0];
                    if (!nodeId.startsWith('topic_')) {{
                        showEvidencePanel(nodeId);
                    }}
                }}
            }});
        }}

        function updateNodeBorders() {{
            // Add red borders to nodes with open issues
            var nodes = network.body.data.nodes;
            var allNodes = nodes.get();

            allNodes.forEach(function(node) {{
                if (!node.id.startsWith('topic_') && issuesByProp[node.id]) {{
                    nodes.update({{
                        id: node.id,
                        borderWidth: 3,
                        color: {{
                            ...node.color,
                            border: '#F44336'
                        }}
                    }});
                }}
            }});
        }}

        function renderIssuesList(statusFilter) {{
            var list = document.getElementById('issues-list');
            var filtered = issuesData.filter(function(i) {{
                if (statusFilter === 'all') return true;
                return i.status === statusFilter;
            }});

            document.getElementById('issue-count').textContent = filtered.length;

            if (filtered.length === 0) {{
                list.innerHTML = '<p style="text-align:center;color:#999;padding:20px;">No issues found</p>';
                return;
            }}

            var html = '';
            filtered.forEach(function(issue) {{
                var resolvedClass = issue.status === 'resolved' ? 'resolved' : '';
                html += '<div class="issue-card ' + resolvedClass + '" onclick="focusIssue(\\'' + issue.id + '\\')">';
                html += '<span class="issue-type ' + issue.type + '">' + issue.type.replace(/_/g, ' ') + '</span>';
                html += '<div class="issue-prop">' + escapeHtml(issue.proposition_name) + '</div>';
                html += '<div class="issue-desc">' + escapeHtml(issue.description) + '</div>';
                if (issue.status === 'open') {{
                    html += '<button style="margin-top:8px;padding:4px 8px;font-size:11px;background:#4CAF50;color:white;border:none;border-radius:3px;cursor:pointer;" onclick="event.stopPropagation();showResolveModal(\\'' + issue.id + '\\')">Resolve</button>';
                }}
                html += '</div>';
            }});

            list.innerHTML = html;
        }}

        function filterIssues(status) {{
            renderIssuesList(status);
        }}

        function focusIssue(issueId) {{
            var issue = issuesData.find(function(i) {{ return i.id === issueId; }});
            if (issue) {{
                // Focus on the proposition node
                network.focus(issue.proposition_id, {{
                    scale: 1.5,
                    animation: {{ duration: 500 }}
                }});
                network.selectNodes([issue.proposition_id]);
                showEvidencePanel(issue.proposition_id);
            }}
        }}

        function showEvidencePanel(propId) {{
            var panel = document.getElementById('evidence-panel');
            var propName = document.getElementById('prop-name');
            var propIdEl = document.getElementById('prop-id');
            var evidenceList = document.getElementById('evidence-list');
            var propIssues = document.getElementById('prop-issues');
            var propIssuesList = document.getElementById('prop-issues-list');

            // Get proposition name from network
            var node = network.body.data.nodes.get(propId);
            propName.textContent = node.label;
            propIdEl.textContent = propId;

            // Get evidence
            var evidence = evidenceData[propId] || [];

            if (evidence.length === 0) {{
                evidenceList.innerHTML = '<p><i>No evidence found</i></p>';
            }} else {{
                var html = '';
                evidence.forEach(function(ev, idx) {{
                    html += '<div class="evidence-item">';
                    html += '<p><strong>Evidence ' + (idx + 1) + ':</strong></p>';
                    html += '<p>' + escapeHtml(ev.claim) + '</p>';
                    html += '<p><small>Source: ' + ev.insight_id + ' (p. ' + ev.pages + ')</small></p>';
                    if (ev.contested_by) {{
                        html += '<p class="contested">⚠ Contested: ' + escapeHtml(ev.contested_by) + '</p>';
                    }}
                    html += '</div>';
                }});
                evidenceList.innerHTML = html;
            }}

            // Show issues for this proposition
            var propIssueItems = issuesByProp[propId] || [];
            if (propIssueItems.length > 0) {{
                var issueHtml = '';
                propIssueItems.forEach(function(issue) {{
                    issueHtml += '<div style="margin-bottom:8px;padding:8px;background:#FFF3E0;border-radius:4px;">';
                    issueHtml += '<span class="issue-type ' + issue.type + '">' + issue.type.replace(/_/g, ' ') + '</span>';
                    issueHtml += '<div style="margin-top:5px;">' + escapeHtml(issue.description) + '</div>';
                    issueHtml += '<button style="margin-top:5px;padding:3px 8px;font-size:11px;background:#4CAF50;color:white;border:none;border-radius:3px;cursor:pointer;" onclick="showResolveModal(\\'' + issue.id + '\\')">Resolve</button>';
                    issueHtml += '</div>';
                }});
                propIssuesList.innerHTML = issueHtml;
                propIssues.style.display = 'block';
            }} else {{
                propIssues.style.display = 'none';
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
                allNodes.forEach(function(node) {{
                    if (!node.id.startsWith('topic_')) {{
                        nodes.update({{id: node.id, hidden: false}});
                    }}
                }});
            }} else {{
                allNodes.forEach(function(node) {{
                    if (!node.id.startsWith('topic_')) {{
                        var inTopic = node.group === topicId;
                        nodes.update({{id: node.id, hidden: !inTopic}});
                    }}
                }});
            }}
        }}

        // Issue Modal Functions
        function showAddIssueModal(preselectedPropId) {{
            var propSelect = document.getElementById('issue-prop-select');
            if (preselectedPropId) {{
                propSelect.value = preselectedPropId;
            }}
            document.getElementById('issue-description').value = '';
            document.getElementById('add-issue-modal').classList.add('active');
        }}

        function showAddIssueModalForProp() {{
            var propId = document.getElementById('prop-id').textContent;
            showAddIssueModal(propId);
        }}

        function closeAddIssueModal() {{
            document.getElementById('add-issue-modal').classList.remove('active');
        }}

        function showResolveModal(issueId) {{
            var issue = issuesData.find(function(i) {{ return i.id === issueId; }});
            if (!issue) return;

            document.getElementById('resolve-issue-id').value = issueId;
            document.getElementById('resolution-text').value = '';

            var detailsHtml = '<p><strong>Proposition:</strong> ' + escapeHtml(issue.proposition_name) + '</p>';
            detailsHtml += '<p><strong>Type:</strong> ' + issue.type.replace(/_/g, ' ') + '</p>';
            detailsHtml += '<p><strong>Description:</strong> ' + escapeHtml(issue.description) + '</p>';
            document.getElementById('resolve-issue-details').innerHTML = detailsHtml;

            document.getElementById('resolve-issue-modal').classList.add('active');
        }}

        function closeResolveModal() {{
            document.getElementById('resolve-issue-modal').classList.remove('active');
        }}

        // File System Access API
        async function connectToFile() {{
            try {{
                if (!('showSaveFilePicker' in window)) {{
                    alert('File System Access API not supported. Changes will not persist. Use Chrome 86+ for full functionality.');
                    return false;
                }}

                fileHandle = await window.showSaveFilePicker({{
                    suggestedName: issuesFilename,
                    types: [{{
                        description: 'JSON Files',
                        accept: {{ 'application/json': ['.json'] }}
                    }}]
                }});

                document.getElementById('file-status').textContent = 'File connected';
                document.getElementById('file-status').classList.add('connected');
                document.getElementById('file-status').style.display = 'inline-block';

                return true;
            }} catch (err) {{
                if (err.name !== 'AbortError') {{
                    console.error('Error connecting to file:', err);
                }}
                return false;
            }}
        }}

        async function saveIssues() {{
            if (!fileHandle) {{
                var connected = await connectToFile();
                if (!connected) {{
                    alert('Could not connect to file. Changes will not persist.');
                    return false;
                }}
            }}

            try {{
                var writable = await fileHandle.createWritable();
                await writable.write(JSON.stringify({{ issues: issuesData }}, null, 2));
                await writable.close();
                return true;
            }} catch (err) {{
                console.error('Error saving issues:', err);
                alert('Error saving: ' + err.message);
                return false;
            }}
        }}

        async function submitNewIssue() {{
            var propId = document.getElementById('issue-prop-select').value;
            var issueType = document.getElementById('issue-type-select').value;
            var description = document.getElementById('issue-description').value.trim();

            if (!propId || !issueType || !description) {{
                alert('Please fill in all fields');
                return;
            }}

            // Get proposition name
            var node = network.body.data.nodes.get(propId);
            var propName = node ? node.label : propId;

            // Generate new ID
            var maxNum = 0;
            issuesData.forEach(function(i) {{
                if (i.id.startsWith('issue_')) {{
                    var num = parseInt(i.id.split('_')[1], 10);
                    if (num > maxNum) maxNum = num;
                }}
            }});
            var newId = 'issue_' + String(maxNum + 1).padStart(3, '0');

            // Create issue
            var newIssue = {{
                id: newId,
                proposition_id: propId,
                proposition_name: propName,
                type: issueType,
                description: description,
                status: 'open',
                created_at: new Date().toISOString(),
                resolved_at: null,
                resolution: null
            }};

            issuesData.push(newIssue);

            // Update issuesByProp
            if (!issuesByProp[propId]) {{
                issuesByProp[propId] = [];
            }}
            issuesByProp[propId].push(newIssue);

            // Save to file
            await saveIssues();

            // Update UI
            updateNodeBorders();
            renderIssuesList(document.getElementById('issue-status-filter').value);
            closeAddIssueModal();

            // If evidence panel is open for this prop, refresh it
            if (document.getElementById('prop-id').textContent === propId) {{
                showEvidencePanel(propId);
            }}
        }}

        async function submitResolveIssue() {{
            var issueId = document.getElementById('resolve-issue-id').value;
            var resolution = document.getElementById('resolution-text').value.trim();

            if (!resolution) {{
                alert('Please enter resolution notes');
                return;
            }}

            // Find and update issue
            var issue = issuesData.find(function(i) {{ return i.id === issueId; }});
            if (!issue) return;

            issue.status = 'resolved';
            issue.resolved_at = new Date().toISOString();
            issue.resolution = resolution;

            // Remove from issuesByProp
            var propId = issue.proposition_id;
            if (issuesByProp[propId]) {{
                issuesByProp[propId] = issuesByProp[propId].filter(function(i) {{
                    return i.id !== issueId;
                }});
                if (issuesByProp[propId].length === 0) {{
                    delete issuesByProp[propId];
                }}
            }}

            // Save to file
            await saveIssues();

            // Update UI
            updateNodeBorders();
            renderIssuesList(document.getElementById('issue-status-filter').value);
            closeResolveModal();

            // If evidence panel is open for this prop, refresh it
            if (document.getElementById('prop-id').textContent === propId) {{
                showEvidencePanel(propId);
            }}
        }}

        function escapeHtml(text) {{
            if (!text) return '';
            var div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}
    </script>
    """

    # Restructure the HTML to wrap PyVis content in our layout
    # PyVis generates: <body><div class="card">...</div></body>
    # We need: <body><div id="app-container"><div id="issues-panel">...</div><div id="main-content">...<div id="graph-container"><div class="card">...</div></div></div></div></body>

    import re

    # Extract the body content
    body_match = re.search(r'<body>(.*?)</body>', html_content, re.DOTALL)
    if body_match:
        original_body = body_match.group(1)

        # Build the new body structure
        new_body = f'''<body>
    <div id="app-container">
        <div id="issues-panel">
            <div id="issues-header">
                <h3>Issues (<span id="issue-count">0</span>)</h3>
                <select id="issue-status-filter" onchange="filterIssues(this.value)">
                    <option value="open">Open</option>
                    <option value="resolved">Resolved</option>
                    <option value="all">All</option>
                </select>
            </div>
            <div id="issues-list"></div>
            <button id="add-issue-btn" onclick="showAddIssueModal()">+ Add Issue</button>
        </div>

        <div id="main-content">
            <div id="controls">
                <label for="topic-filter">Filter by topic:</label>
                <select id="topic-filter" onchange="filterByTopic(this.value)">
                    <option value="all">All Topics</option>
                </select>

                <span id="file-status">File not connected</span>

                <div class="legend">
                    <div class="legend-item">
                        <span class="legend-box" style="background-color: #4CAF50;"></span>
                        <span>Grounded</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-box" style="background-color: #FFC107;"></span>
                        <span>Partial</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-box" style="background-color: #F44336;"></span>
                        <span>Gap</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-box" style="background-color: white; border: 3px solid #F44336;"></span>
                        <span>Has Issue</span>
                    </div>
                </div>
            </div>

            <div id="graph-container">
                {original_body}
            </div>
        </div>
    </div>

    <div id="evidence-panel">
        <span class="close-btn" onclick="closeEvidencePanel()">&times;</span>
        <h3 id="prop-name"></h3>
        <div id="prop-id" style="display:none;"></div>
        <div id="evidence-list"></div>
        <div id="prop-issues" class="prop-issues" style="display:none;">
            <h4>Open Issues</h4>
            <div id="prop-issues-list"></div>
        </div>
        <button id="add-issue-to-prop-btn" onclick="showAddIssueModalForProp()">+ Add Issue</button>
    </div>

    <!-- Add Issue Modal -->
    <div id="add-issue-modal" class="modal-overlay">
        <div class="modal">
            <h3>Add Issue</h3>
            <label for="issue-prop-select">Proposition:</label>
            <select id="issue-prop-select"></select>

            <label for="issue-type-select">Issue Type:</label>
            <select id="issue-type-select"></select>

            <label for="issue-description">Description:</label>
            <textarea id="issue-description" placeholder="Describe the issue..."></textarea>

            <div class="modal-buttons">
                <button class="btn-cancel" onclick="closeAddIssueModal()">Cancel</button>
                <button class="btn-submit" onclick="submitNewIssue()">Add Issue</button>
            </div>
        </div>
    </div>

    <!-- Resolve Issue Modal -->
    <div id="resolve-issue-modal" class="modal-overlay">
        <div class="modal">
            <h3>Resolve Issue</h3>
            <div id="resolve-issue-details"></div>

            <label for="resolution-text">Resolution Notes:</label>
            <textarea id="resolution-text" placeholder="How was this issue resolved?"></textarea>

            <input type="hidden" id="resolve-issue-id">

            <div class="modal-buttons">
                <button class="btn-cancel" onclick="closeResolveModal()">Cancel</button>
                <button class="btn-submit" onclick="submitResolveIssue()">Resolve</button>
            </div>
        </div>
    </div>

    {custom_html}
</body>'''

        html_content = html_content.replace(body_match.group(0), new_body)

    # Write modified HTML back
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    # Get stats
    stats = db.get_argument_map_stats(project)

    return {
        'success': True,
        'project': project,
        'output_path': output_path,
        'stats': stats,
        'topics_count': len(topics),
        'message': f"Interactive argument map saved to {output_path}. "
                  f"Open in browser to explore {len(topics)} topics, {stats['total_propositions']} propositions, "
                  f"and {stats['relationships']} relationships. "
                  f"Click propositions to see evidence details. Use topic filter to focus."
    }


# ============================================================================
# Issue Tracking Functions
# ============================================================================

# Valid issue types
ISSUE_TYPES = [
    'needs_evidence',  # Needs more literature support
    'rephrase',        # Wording needs improvement
    'wrong_topic',     # Assigned to wrong topic
    'merge',           # Should be merged with another proposition
    'split',           # Should be split into multiple propositions
    'delete',          # Should be removed
    'question',        # General question/note
    'other',           # Freeform
]


def _get_issues_path(project: str) -> Path:
    """Get the path to the project's issues JSON file."""
    lit_path = config_manager.literature_path
    if not lit_path:
        return None
    return lit_path / project / "_issues.json"


def _load_issues(project: str) -> dict:
    """Load issues from the project's JSON file."""
    issues_path = _get_issues_path(project)
    if not issues_path or not issues_path.exists():
        return {"issues": []}

    try:
        with open(issues_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"issues": []}


def _save_issues(project: str, data: dict) -> bool:
    """Save issues to the project's JSON file."""
    issues_path = _get_issues_path(project)
    if not issues_path:
        return False

    # Ensure parent directory exists
    issues_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(issues_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except IOError:
        return False


def _generate_issue_id(existing_issues: list) -> str:
    """Generate a unique issue ID."""
    from datetime import datetime

    # Find the highest existing issue number
    max_num = 0
    for issue in existing_issues:
        if issue.get('id', '').startswith('issue_'):
            try:
                num = int(issue['id'].split('_')[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                pass

    return f"issue_{max_num + 1:03d}"


def add_proposition_issue(
    project: str,
    proposition_id: str,
    issue_type: str,
    description: str,
) -> dict:
    """
    Add an issue to a proposition for tracking needed changes.

    Args:
        project: Project code
        proposition_id: The proposition ID to attach the issue to
        issue_type: Type of issue (needs_evidence, rephrase, wrong_topic, merge, split, delete, question, other)
        description: Description of the issue

    Returns:
        Success status and created issue
    """
    from datetime import datetime

    # Validate issue type
    if issue_type not in ISSUE_TYPES:
        return {
            'success': False,
            'error': f"Invalid issue type '{issue_type}'. Must be one of: {', '.join(ISSUE_TYPES)}"
        }

    # Initialize schema to check proposition exists
    db.init_argument_map_schema()

    # Get proposition info
    proposition = db.get_proposition(proposition_id)
    if not proposition:
        return {
            'success': False,
            'error': f"Proposition not found: {proposition_id}"
        }

    # Load existing issues
    data = _load_issues(project)

    # Create new issue
    issue_id = _generate_issue_id(data['issues'])
    new_issue = {
        'id': issue_id,
        'proposition_id': proposition_id,
        'proposition_name': proposition['name'],
        'type': issue_type,
        'description': description,
        'status': 'open',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'resolved_at': None,
        'resolution': None
    }

    data['issues'].append(new_issue)

    # Save
    if not _save_issues(project, data):
        return {
            'success': False,
            'error': 'Failed to save issues file'
        }

    return {
        'success': True,
        'issue': new_issue,
        'message': f"Created issue {issue_id}: {issue_type} for '{proposition['name']}'"
    }


def list_proposition_issues(
    project: str,
    status: str = 'all',
    proposition_id: Optional[str] = None,
) -> dict:
    """
    List issues for a project.

    Args:
        project: Project code
        status: Filter by status ('all', 'open', 'resolved')
        proposition_id: Optional filter by specific proposition

    Returns:
        List of matching issues
    """
    data = _load_issues(project)
    issues = data['issues']

    # Filter by status
    if status == 'open':
        issues = [i for i in issues if i['status'] == 'open']
    elif status == 'resolved':
        issues = [i for i in issues if i['status'] == 'resolved']

    # Filter by proposition
    if proposition_id:
        issues = [i for i in issues if i['proposition_id'] == proposition_id]

    # Count by type
    type_counts = {}
    for issue in issues:
        issue_type = issue.get('type', 'unknown')
        type_counts[issue_type] = type_counts.get(issue_type, 0) + 1

    return {
        'success': True,
        'project': project,
        'status_filter': status,
        'issues': issues,
        'count': len(issues),
        'by_type': type_counts,
        'message': f"Found {len(issues)} issues"
    }


def resolve_proposition_issue(
    project: str,
    issue_id: str,
    resolution: str,
) -> dict:
    """
    Mark an issue as resolved.

    Args:
        project: Project code
        issue_id: The issue ID to resolve
        resolution: Notes on how the issue was resolved

    Returns:
        Success status
    """
    from datetime import datetime

    data = _load_issues(project)

    # Find the issue
    issue = None
    for i in data['issues']:
        if i['id'] == issue_id:
            issue = i
            break

    if not issue:
        return {
            'success': False,
            'error': f"Issue not found: {issue_id}"
        }

    if issue['status'] == 'resolved':
        return {
            'success': False,
            'error': f"Issue {issue_id} is already resolved"
        }

    # Update issue
    issue['status'] = 'resolved'
    issue['resolved_at'] = datetime.utcnow().isoformat() + 'Z'
    issue['resolution'] = resolution

    # Save
    if not _save_issues(project, data):
        return {
            'success': False,
            'error': 'Failed to save issues file'
        }

    return {
        'success': True,
        'issue': issue,
        'message': f"Resolved issue {issue_id}: {issue['type']} for '{issue['proposition_name']}'"
    }


def list_evidence(
    proposition_id: str,
    project: Optional[str] = None,
) -> dict:
    """
    List evidence entries for a proposition.

    Args:
        proposition_id: The proposition ID to list evidence for
        project: Optional project code to filter by

    Returns:
        List of evidence entries with IDs
    """
    db.init_argument_map_schema()

    # Verify proposition exists
    proposition = db.get_proposition(proposition_id)
    if not proposition:
        return {
            'success': False,
            'error': f"Proposition '{proposition_id}' not found"
        }

    evidence = db.get_evidence(proposition_id, project)

    return {
        'success': True,
        'proposition_id': proposition_id,
        'proposition_name': proposition['name'],
        'project_filter': project,
        'evidence': evidence,
        'count': len(evidence),
        'message': f"Found {len(evidence)} evidence entries for '{proposition['name']}'"
    }


def delete_evidence(
    evidence_id: int,
    confirm: bool = False,
) -> dict:
    """
    Delete an evidence entry by ID.

    Args:
        evidence_id: Integer ID of the evidence entry to delete
        confirm: Must be True to proceed (safety check)

    Returns:
        Success status
    """
    if not confirm:
        return {
            'success': False,
            'error': "Must set confirm=True to delete evidence. This action cannot be undone."
        }

    db.init_argument_map_schema()

    # Verify evidence exists before deleting
    conn = db.get_connection()
    row = conn.execute(
        "SELECT id, proposition_id, claim FROM proposition_evidence WHERE id = ?",
        [evidence_id]
    ).fetchone()

    if not row:
        return {
            'success': False,
            'error': f"Evidence entry with id={evidence_id} not found"
        }

    db.delete_evidence(evidence_id)

    return {
        'success': True,
        'evidence_id': evidence_id,
        'proposition_id': row[1],
        'message': f"Deleted evidence entry {evidence_id} from proposition '{row[1]}'"
    }


def delete_proposition_issue(
    project: str,
    issue_id: str,
    confirm: bool = False,
) -> dict:
    """
    Delete an issue.

    Args:
        project: Project code
        issue_id: The issue ID to delete
        confirm: Must be True to proceed

    Returns:
        Success status
    """
    if not confirm:
        return {
            'success': False,
            'error': 'Must set confirm=True to delete an issue'
        }

    data = _load_issues(project)

    # Find and remove the issue
    original_count = len(data['issues'])
    data['issues'] = [i for i in data['issues'] if i['id'] != issue_id]

    if len(data['issues']) == original_count:
        return {
            'success': False,
            'error': f"Issue not found: {issue_id}"
        }

    # Save
    if not _save_issues(project, data):
        return {
            'success': False,
            'error': 'Failed to save issues file'
        }

    return {
        'success': True,
        'message': f"Deleted issue {issue_id}"
    }
