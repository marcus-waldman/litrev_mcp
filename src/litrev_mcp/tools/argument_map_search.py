"""
GraphRAG-style semantic search and traversal for the argument map.

Provides three MCP tools:
- embed_propositions: Generate embeddings for all propositions in a project
- search_argument_map: Semantic search with LLM-judged graph traversal
- expand_argument_map: Manual expansion from specific propositions
"""

import json
import os
from typing import Optional, Any

from litrev_mcp.tools.rag_db import get_connection, checkpoint
from litrev_mcp.tools.rag_embed import embed_texts, embed_query, EmbeddingError
from litrev_mcp.tools import argument_map_db as db


def _build_embedding_text(name: str, definition: Optional[str]) -> str:
    """Build the text to embed for a proposition."""
    if definition:
        return f"{name}: {definition}"
    return name


# ============================================================================
# MCP Tool: embed_propositions
# ============================================================================

def embed_propositions(
    project: str,
    force: bool = False,
) -> dict:
    """
    Generate embeddings for all propositions in a project's argument map.

    Required before using search_argument_map. Embeds proposition names and
    definitions using OpenAI text-embedding-3-small. Skips already-embedded
    propositions unless force=True. Re-embeds stale propositions whose
    name/definition changed since last embedding.
    """
    db.init_argument_map_schema()

    propositions = db.get_project_propositions(project)
    if not propositions:
        return {
            'success': True,
            'project': project,
            'message': 'No propositions found in project',
            'embedded': 0,
            'skipped': 0,
        }

    # Determine which need embedding
    conn = get_connection()
    to_embed = []
    skipped = 0

    for prop in propositions:
        embed_text = _build_embedding_text(prop['name'], prop['definition'])

        if not force:
            existing = conn.execute(
                "SELECT embedded_text FROM proposition_embeddings WHERE proposition_id = ?",
                [prop['id']]
            ).fetchone()

            if existing and existing[0] == embed_text:
                skipped += 1
                continue

        to_embed.append({
            'id': prop['id'],
            'text': embed_text,
        })

    if not to_embed:
        return {
            'success': True,
            'project': project,
            'message': 'All propositions already embedded',
            'embedded': 0,
            'skipped': skipped,
        }

    try:
        # Batch embed (100 at a time)
        BATCH_SIZE = 100
        total_embedded = 0

        for i in range(0, len(to_embed), BATCH_SIZE):
            batch = to_embed[i:i + BATCH_SIZE]
            texts = [item['text'] for item in batch]
            embeddings = embed_texts(texts)

            for item, embedding in zip(batch, embeddings):
                db.upsert_proposition_embedding(
                    item['id'], embedding, item['text']
                )
                total_embedded += 1

        checkpoint()

        return {
            'success': True,
            'project': project,
            'embedded': total_embedded,
            'skipped': skipped,
            'message': f"Embedded {total_embedded} propositions, skipped {skipped} (already current)",
        }

    except EmbeddingError as e:
        return {
            'success': False,
            'error': str(e),
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"Embedding failed: {str(e)}",
        }


# ============================================================================
# Internal: LLM-judged traversal parameters
# ============================================================================

def _judge_traversal_params(
    query: str,
    seed_propositions: list[dict],
) -> dict:
    """
    Use Claude Sonnet to determine traversal parameters based on query intent.

    Returns dict with: hop_depth, relationship_types, max_neighbors_per_hop, reasoning.
    Falls back to sensible defaults on any error.
    """
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {
            'hop_depth': 1,
            'relationship_types': None,
            'max_neighbors_per_hop': 10,
            'reasoning': 'Default parameters (ANTHROPIC_API_KEY not set)',
        }

    seed_summary = "\n".join([
        f"- {s['name']}: {(s.get('definition') or 'No definition')[:100]}"
        for s in seed_propositions[:5]
    ])

    prompt = f"""You are analyzing a query against an argument map to determine how deeply to explore relationships.

QUERY: {query}

SEED PROPOSITIONS (most semantically similar to query):
{seed_summary}

AVAILABLE RELATIONSHIP TYPES:
- Argumentative: supports, contradicts, extends, qualifies, necessitates
- Logical: leads_to, precedes, enables, depends_on

Determine the optimal traversal parameters. Consider:
- A focused/specific query (e.g., "what supports X?") needs fewer hops but specific relationship types
- A broad/exploratory query (e.g., "what is the full argument around X?") needs more hops and all types
- A causal/chain query (e.g., "what leads to X?") needs directed traversal along logical types
- If seeds already look highly relevant, fewer hops may suffice

Return ONLY a JSON object:
{{
    "hop_depth": <1-3>,
    "relationship_types": <list of types to follow, or null for all>,
    "max_neighbors_per_hop": <5-20>,
    "reasoning": "<one sentence explaining why>"
}}"""

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = message.content[0].text

        # Parse JSON (may be wrapped in code blocks)
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

        params = json.loads(json_text)

        # Validate and clamp
        params['hop_depth'] = max(1, min(3, params.get('hop_depth', 1)))
        params['max_neighbors_per_hop'] = max(5, min(20, params.get('max_neighbors_per_hop', 10)))

        if params.get('relationship_types') is not None:
            valid_types = {
                'supports', 'contradicts', 'extends', 'qualifies', 'necessitates',
                'leads_to', 'precedes', 'enables', 'depends_on',
            }
            params['relationship_types'] = [
                t for t in params['relationship_types'] if t in valid_types
            ]
            if not params['relationship_types']:
                params['relationship_types'] = None

        return params

    except Exception as e:
        return {
            'hop_depth': 1,
            'relationship_types': None,
            'max_neighbors_per_hop': 10,
            'reasoning': f'Default parameters (LLM call failed: {str(e)[:80]})',
        }


# ============================================================================
# Internal: Graph traversal
# ============================================================================

def _traverse_graph(
    seeds: list[dict],
    params: dict,
    project: str,
) -> dict:
    """
    BFS expansion from seed propositions along relationships.

    Returns dict with:
        propositions: {id -> prop_dict}
        relationships: [edge_dicts]
        hop_layers: [[ids at each hop depth]]
    """
    visited_ids: set[str] = set()
    all_propositions: dict[str, dict] = {}
    all_relationships: list[dict] = []
    hop_layers: list[list[str]] = []

    # Initialize with seeds
    frontier: list[str] = []
    for seed in seeds:
        prop_id = seed['proposition_id']
        visited_ids.add(prop_id)
        all_propositions[prop_id] = seed
        frontier.append(prop_id)

    hop_layers.append(list(frontier))

    hop_depth = params.get('hop_depth', 1)
    relationship_types = params.get('relationship_types', None)
    max_per_hop = params.get('max_neighbors_per_hop', 10)

    for _hop in range(hop_depth):
        if not frontier:
            break

        result = db.get_proposition_neighbors(
            proposition_ids=frontier,
            relationship_types=relationship_types,
            project=project,
        )

        all_relationships.extend(result['relationships'])

        # Collect new (unvisited) neighbors
        new_neighbors: list[dict] = []
        for prop in result['propositions']:
            pid = prop['proposition_id']
            if pid not in visited_ids:
                new_neighbors.append(prop)

        # Cap to prevent explosion in dense graphs
        if len(new_neighbors) > max_per_hop:
            new_neighbors = new_neighbors[:max_per_hop]

        # Add capped set to results and frontier
        new_frontier: list[str] = []
        for prop in new_neighbors:
            pid = prop['proposition_id']
            visited_ids.add(pid)
            all_propositions[pid] = prop
            new_frontier.append(pid)

        if new_frontier:
            hop_layers.append(new_frontier)

        frontier = new_frontier

    # Deduplicate relationships
    seen_rels: set[tuple] = set()
    unique_relationships: list[dict] = []
    for rel in all_relationships:
        key = (rel['from_proposition_id'], rel['to_proposition_id'], rel['relationship_type'])
        if key not in seen_rels:
            seen_rels.add(key)
            unique_relationships.append(rel)

    return {
        'propositions': all_propositions,
        'relationships': unique_relationships,
        'hop_layers': hop_layers,
    }


def _collect_evidence(
    proposition_ids: list[str],
    project: str,
) -> dict[str, list[dict]]:
    """Collect evidence for all propositions in the subgraph."""
    evidence_by_prop: dict[str, list[dict]] = {}
    for pid in proposition_ids:
        evidence_list = db.get_evidence(pid, project)
        if evidence_list:
            evidence_by_prop[pid] = evidence_list
    return evidence_by_prop


# ============================================================================
# MCP Tool: search_argument_map
# ============================================================================

def search_argument_map(
    project: str,
    query: str,
    max_results: int = 10,
) -> dict:
    """
    Semantic search over the argument map with LLM-judged graph traversal.

    Pipeline:
    1. Embed the query via OpenAI
    2. Find seed propositions via vector similarity
    3. Call Claude Sonnet to judge traversal parameters from query intent
    4. Expand from seeds along relationships (BFS)
    5. Collect evidence for the subgraph
    6. Return focused subgraph with propositions, relationships, evidence
    """
    db.init_argument_map_schema()

    # Check embedding status
    status = db.get_embedding_status(project)
    if status['embedded'] == 0:
        return {
            'success': False,
            'error': 'NO_EMBEDDINGS',
            'message': (
                f"No proposition embeddings found for project '{project}'. "
                f"Run embed_propositions first to generate embeddings for "
                f"{status['total_propositions']} propositions."
            ),
            'guidance': 'Use the embed_propositions tool with this project to create embeddings.',
        }

    embedding_warning = None
    if status['not_embedded'] > 0:
        embedding_warning = (
            f"{status['not_embedded']} of {status['total_propositions']} propositions "
            f"are not yet embedded. Results may be incomplete."
        )

    try:
        # Step 1: Embed query
        query_embedding = embed_query(query)

        # Step 2: Find seeds
        num_seeds = min(max_results, 5)
        seeds = db.search_similar_propositions(
            query_embedding=query_embedding,
            project=project,
            max_results=num_seeds,
            min_score=0.3,
        )

        if not seeds:
            return {
                'success': True,
                'project': project,
                'query': query,
                'subgraph': {'propositions': [], 'relationships': []},
                'message': (
                    'No semantically similar propositions found. '
                    'Try a different query or add more propositions to the map.'
                ),
            }

        # Step 3: Judge traversal parameters
        traversal_params = _judge_traversal_params(query, seeds)

        # Step 4: Traverse graph
        graph = _traverse_graph(seeds, traversal_params, project)

        # Step 5: Collect evidence
        all_prop_ids = list(graph['propositions'].keys())
        evidence = _collect_evidence(all_prop_ids, project)

        # Step 6: Build result
        seed_ids = {s['proposition_id'] for s in seeds}
        seed_scores = {s['proposition_id']: s.get('score', 0) for s in seeds}

        propositions_list = []
        for pid, prop in graph['propositions'].items():
            prop_evidence = evidence.get(pid, [])
            topics = db.get_proposition_topics(pid)

            propositions_list.append({
                'proposition_id': pid,
                'name': prop.get('name', ''),
                'definition': prop.get('definition', ''),
                'source': prop.get('source', ''),
                'score': seed_scores.get(pid),
                'is_seed': pid in seed_ids,
                'evidence_count': len(prop_evidence),
                'evidence': [
                    {'claim': ev['claim'], 'insight_id': ev['insight_id'], 'pages': ev.get('pages')}
                    for ev in prop_evidence[:3]
                ],
                'topics': [t['name'] for t in topics],
            })

        # Sort: seeds first (by score desc), then others
        propositions_list.sort(
            key=lambda p: (
                not p.get('is_seed', False),
                -(p.get('score') or 0),
            )
        )

        # Limit total results
        if len(propositions_list) > max_results:
            propositions_list = propositions_list[:max_results]

        result: dict[str, Any] = {
            'success': True,
            'project': project,
            'query': query,
            'traversal': {
                'seeds_found': len(seeds),
                'hop_depth': traversal_params.get('hop_depth', 1),
                'relationship_types': traversal_params.get('relationship_types', 'all'),
                'reasoning': traversal_params.get('reasoning', ''),
                'total_propositions_in_subgraph': len(graph['propositions']),
                'total_relationships_in_subgraph': len(graph['relationships']),
            },
            'subgraph': {
                'propositions': propositions_list,
                'relationships': graph['relationships'],
            },
            'message': (
                f"Found {len(seeds)} seed propositions, "
                f"expanded to {len(graph['propositions'])} via "
                f"{traversal_params.get('hop_depth', 1)}-hop traversal. "
                f"Returning top {len(propositions_list)} with "
                f"{len(graph['relationships'])} relationships."
            ),
        }

        if embedding_warning:
            result['warning'] = embedding_warning

        return result

    except EmbeddingError as e:
        return {
            'success': False,
            'error': 'EMBEDDING_ERROR',
            'message': str(e),
        }
    except Exception as e:
        return {
            'success': False,
            'error': 'SEARCH_ERROR',
            'message': str(e),
        }


# ============================================================================
# MCP Tool: expand_argument_map
# ============================================================================

def expand_argument_map(
    project: str,
    proposition_ids: list[str],
    hop_depth: int = 1,
    relationship_types: Optional[list[str]] = None,
) -> dict:
    """
    Manually expand from specific propositions in the argument map.

    Use this to explore further from propositions returned by search_argument_map.
    No LLM call or embedding search — directly follows relationships outward.
    """
    db.init_argument_map_schema()

    # Validate proposition IDs
    valid_ids = []
    invalid_ids = []
    for pid in proposition_ids:
        if db.proposition_exists(pid):
            valid_ids.append(pid)
        else:
            invalid_ids.append(pid)

    if not valid_ids:
        return {
            'success': False,
            'error': 'No valid proposition IDs provided',
            'invalid_ids': invalid_ids,
        }

    # Build seed props
    seeds = []
    for pid in valid_ids:
        prop = db.get_proposition(pid)
        if prop:
            seeds.append({
                'proposition_id': prop['id'],
                'name': prop['name'],
                'definition': prop['definition'],
                'source': prop['source'],
            })

    params = {
        'hop_depth': max(1, min(3, hop_depth)),
        'relationship_types': relationship_types,
        'max_neighbors_per_hop': 15,
    }

    graph = _traverse_graph(seeds, params, project)

    # Collect evidence
    all_prop_ids = list(graph['propositions'].keys())
    evidence = _collect_evidence(all_prop_ids, project)

    propositions_list = []
    for pid, prop in graph['propositions'].items():
        prop_evidence = evidence.get(pid, [])
        propositions_list.append({
            'proposition_id': pid,
            'name': prop.get('name', ''),
            'definition': prop.get('definition', ''),
            'source': prop.get('source', ''),
            'is_origin': pid in set(valid_ids),
            'evidence_count': len(prop_evidence),
            'evidence': [
                {'claim': ev['claim'], 'insight_id': ev['insight_id']}
                for ev in prop_evidence[:3]
            ],
        })

    result: dict[str, Any] = {
        'success': True,
        'project': project,
        'origin_propositions': valid_ids,
        'subgraph': {
            'propositions': propositions_list,
            'relationships': graph['relationships'],
        },
        'hop_layers': graph['hop_layers'],
        'message': (
            f"Expanded from {len(valid_ids)} propositions: found "
            f"{len(graph['propositions'])} total propositions and "
            f"{len(graph['relationships'])} relationships across "
            f"{len(graph['hop_layers'])} layers."
        ),
    }

    if invalid_ids:
        result['invalid_ids'] = invalid_ids

    return result
