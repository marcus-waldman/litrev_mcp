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

from litrev_mcp.config import config_manager
from litrev_mcp.tools import concept_map_db as db


def _make_concept_id(name: str) -> str:
    """Generate a concept ID from the concept name."""
    # Convert to lowercase, replace spaces/special chars with underscores
    concept_id = re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return concept_id


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
