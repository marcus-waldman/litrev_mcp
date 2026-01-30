"""
Tests for argument map search (GraphRAG-style traversal).

Tests embedding text building, DB operations for proposition embeddings,
neighbor queries, traversal logic, and MCP tool functions.
"""

import sys
import pytest
import json
from unittest.mock import patch, MagicMock


def _mock_anthropic():
    """Create a mock anthropic module for tests where it's not installed."""
    mock_module = MagicMock()
    return mock_module

from litrev_mcp.tools.argument_map_search import (
    _build_embedding_text,
    _traverse_graph,
    _collect_evidence,
    _judge_traversal_params,
    embed_propositions,
    search_argument_map,
    expand_argument_map,
)


class TestBuildEmbeddingText:
    """Tests for _build_embedding_text helper."""

    def test_with_definition(self):
        text = _build_embedding_text("X causes Y", "When X happens, Y follows")
        assert text == "X causes Y: When X happens, Y follows"

    def test_without_definition(self):
        text = _build_embedding_text("X causes Y", None)
        assert text == "X causes Y"

    def test_empty_definition(self):
        text = _build_embedding_text("X causes Y", "")
        assert text == "X causes Y"


class TestTraverseGraph:
    """Tests for _traverse_graph BFS logic."""

    def test_no_seeds(self):
        """Empty seeds should return empty graph."""
        result = _traverse_graph([], {'hop_depth': 1}, 'test')
        assert result['propositions'] == {}
        assert result['relationships'] == []
        assert result['hop_layers'] == [[]]

    def test_seeds_only_no_expansion(self):
        """With hop_depth=0-like behavior (no neighbors), just seeds returned."""
        seeds = [
            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
        ]

        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': [],
                'relationships': [],
            }

            result = _traverse_graph(seeds, {'hop_depth': 1}, 'test')

            assert 'a' in result['propositions']
            assert len(result['hop_layers']) == 1
            assert result['hop_layers'][0] == ['a']

    def test_one_hop_expansion(self):
        """One hop should find direct neighbors."""
        seeds = [
            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
        ]

        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': [
                    {'proposition_id': 'b', 'name': 'B', 'definition': 'Def B', 'source': 'insight'},
                ],
                'relationships': [
                    {
                        'id': 1,
                        'from_proposition_id': 'a',
                        'from_name': 'A',
                        'to_proposition_id': 'b',
                        'to_name': 'B',
                        'relationship_type': 'supports',
                        'source': 'insight',
                        'grounded_in': None,
                    },
                ],
            }

            result = _traverse_graph(seeds, {'hop_depth': 1}, 'test')

            assert 'a' in result['propositions']
            assert 'b' in result['propositions']
            assert len(result['relationships']) == 1
            assert len(result['hop_layers']) == 2

    def test_cycle_prevention(self):
        """Visited nodes should not be re-added."""
        seeds = [
            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
        ]

        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            # First hop: a -> b
            # Second hop: b -> a (cycle) + b -> c
            call_count = [0]

            def mock_neighbors(proposition_ids, relationship_types=None, project=None):
                call_count[0] += 1
                if call_count[0] == 1:
                    return {
                        'propositions': [
                            {'proposition_id': 'b', 'name': 'B', 'definition': 'Def B', 'source': 'insight'},
                        ],
                        'relationships': [
                            {'id': 1, 'from_proposition_id': 'a', 'from_name': 'A',
                             'to_proposition_id': 'b', 'to_name': 'B',
                             'relationship_type': 'supports', 'source': 'insight', 'grounded_in': None},
                        ],
                    }
                else:
                    # b's neighbors include a (already visited) and c (new)
                    return {
                        'propositions': [
                            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
                            {'proposition_id': 'c', 'name': 'C', 'definition': 'Def C', 'source': 'insight'},
                        ],
                        'relationships': [
                            {'id': 2, 'from_proposition_id': 'b', 'from_name': 'B',
                             'to_proposition_id': 'a', 'to_name': 'A',
                             'relationship_type': 'contradicts', 'source': 'insight', 'grounded_in': None},
                            {'id': 3, 'from_proposition_id': 'b', 'from_name': 'B',
                             'to_proposition_id': 'c', 'to_name': 'C',
                             'relationship_type': 'extends', 'source': 'insight', 'grounded_in': None},
                        ],
                    }

            mock_db.get_proposition_neighbors.side_effect = mock_neighbors

            result = _traverse_graph(seeds, {'hop_depth': 2}, 'test')

            # a, b, c should be in the graph but a should only appear once
            assert len(result['propositions']) == 3
            assert 'a' in result['propositions']
            assert 'b' in result['propositions']
            assert 'c' in result['propositions']

    def test_frontier_cap(self):
        """Frontier should be capped at max_neighbors_per_hop."""
        seeds = [
            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
        ]

        # Return 10 neighbors but cap at 3
        many_neighbors = [
            {'proposition_id': f'n{i}', 'name': f'N{i}', 'definition': f'Def N{i}', 'source': 'insight'}
            for i in range(10)
        ]

        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': many_neighbors,
                'relationships': [],
            }

            result = _traverse_graph(seeds, {'hop_depth': 1, 'max_neighbors_per_hop': 3}, 'test')

            # Should have seed + 3 capped neighbors = 4 total
            assert len(result['propositions']) == 4

    def test_relationship_deduplication(self):
        """Duplicate relationships should be deduplicated."""
        seeds = [
            {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight'},
        ]
        rel = {
            'id': 1, 'from_proposition_id': 'a', 'from_name': 'A',
            'to_proposition_id': 'b', 'to_name': 'B',
            'relationship_type': 'supports', 'source': 'insight', 'grounded_in': None,
        }

        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': [
                    {'proposition_id': 'b', 'name': 'B', 'definition': 'Def B', 'source': 'insight'},
                ],
                'relationships': [rel, rel],  # duplicate
            }

            result = _traverse_graph(seeds, {'hop_depth': 1}, 'test')
            assert len(result['relationships']) == 1


class TestJudgeTraversalParams:
    """Tests for _judge_traversal_params."""

    def test_fallback_no_api_key(self):
        """Without ANTHROPIC_API_KEY, should return defaults."""
        with patch.dict('os.environ', {}, clear=True):
            params = _judge_traversal_params("test query", [])

        assert params['hop_depth'] == 1
        assert params['relationship_types'] is None
        assert params['max_neighbors_per_hop'] == 10

    def test_fallback_on_error(self):
        """On any API error, should return defaults."""
        mock_anthropic = _mock_anthropic()
        mock_anthropic.Anthropic.side_effect = Exception("API error")

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'anthropic': mock_anthropic}):
                params = _judge_traversal_params("test query", [])

        assert params['hop_depth'] == 1
        assert params['relationship_types'] is None

    def test_parses_valid_response(self):
        """Should parse valid JSON response from LLM."""
        mock_anthropic = _mock_anthropic()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            'hop_depth': 2,
            'relationship_types': ['supports', 'contradicts'],
            'max_neighbors_per_hop': 15,
            'reasoning': 'Broad query needs more depth',
        }))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'anthropic': mock_anthropic}):
                params = _judge_traversal_params("what is the full argument?", [
                    {'name': 'Test', 'definition': 'A test prop'},
                ])

        assert params['hop_depth'] == 2
        assert params['relationship_types'] == ['supports', 'contradicts']
        assert params['max_neighbors_per_hop'] == 15

    def test_clamps_values(self):
        """Should clamp hop_depth and max_neighbors_per_hop."""
        mock_anthropic = _mock_anthropic()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            'hop_depth': 99,
            'relationship_types': None,
            'max_neighbors_per_hop': 500,
            'reasoning': 'Extreme values',
        }))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'anthropic': mock_anthropic}):
                params = _judge_traversal_params("test", [])

        assert params['hop_depth'] == 3  # clamped
        assert params['max_neighbors_per_hop'] == 20  # clamped

    def test_filters_invalid_relationship_types(self):
        """Should filter out invalid relationship types."""
        mock_anthropic = _mock_anthropic()
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=json.dumps({
            'hop_depth': 1,
            'relationship_types': ['supports', 'invalid_type', 'contradicts'],
            'max_neighbors_per_hop': 10,
            'reasoning': 'Test',
        }))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key'}):
            with patch.dict('sys.modules', {'anthropic': mock_anthropic}):
                params = _judge_traversal_params("test", [])

        assert params['relationship_types'] == ['supports', 'contradicts']


class TestSearchArgumentMap:
    """Tests for search_argument_map MCP tool."""

    def test_no_embeddings_error(self):
        """Should return clear error when no embeddings exist."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_embedding_status.return_value = {
                'total_propositions': 5,
                'embedded': 0,
                'not_embedded': 5,
                'stale': 0,
            }

            result = search_argument_map('test_project', 'some query')

        assert result['success'] is False
        assert result['error'] == 'NO_EMBEDDINGS'
        assert 'embed_propositions' in result['message']

    def test_no_similar_results(self):
        """Should return empty subgraph gracefully."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_embedding_status.return_value = {
                'total_propositions': 5,
                'embedded': 5,
                'not_embedded': 0,
                'stale': 0,
            }
            mock_db.search_similar_propositions.return_value = []

            with patch('litrev_mcp.tools.argument_map_search.embed_query') as mock_embed:
                mock_embed.return_value = [0.1] * 1536

                result = search_argument_map('test_project', 'totally irrelevant query')

        assert result['success'] is True
        assert result['subgraph']['propositions'] == []

    def test_full_pipeline(self):
        """Test full search pipeline with mocked components."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_embedding_status.return_value = {
                'total_propositions': 10,
                'embedded': 10,
                'not_embedded': 0,
                'stale': 0,
            }
            mock_db.search_similar_propositions.return_value = [
                {'proposition_id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight', 'score': 0.85},
            ]
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': [
                    {'proposition_id': 'b', 'name': 'B', 'definition': 'Def B', 'source': 'insight'},
                ],
                'relationships': [
                    {'id': 1, 'from_proposition_id': 'a', 'from_name': 'A',
                     'to_proposition_id': 'b', 'to_name': 'B',
                     'relationship_type': 'supports', 'source': 'insight', 'grounded_in': None},
                ],
            }
            mock_db.get_evidence.return_value = []
            mock_db.get_proposition_topics.return_value = [{'name': 'Topic 1'}]

            with patch('litrev_mcp.tools.argument_map_search.embed_query') as mock_embed:
                mock_embed.return_value = [0.1] * 1536

                with patch('litrev_mcp.tools.argument_map_search._judge_traversal_params') as mock_judge:
                    mock_judge.return_value = {
                        'hop_depth': 1,
                        'relationship_types': None,
                        'max_neighbors_per_hop': 10,
                        'reasoning': 'Test',
                    }

                    result = search_argument_map('test_project', 'test query')

        assert result['success'] is True
        assert len(result['subgraph']['propositions']) == 2
        assert result['traversal']['seeds_found'] == 1
        # Seed should be first
        assert result['subgraph']['propositions'][0]['is_seed'] is True


class TestExpandArgumentMap:
    """Tests for expand_argument_map MCP tool."""

    def test_invalid_ids(self):
        """Should return error when no valid IDs provided."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.proposition_exists.return_value = False

            result = expand_argument_map('test_project', ['nonexistent'])

        assert result['success'] is False
        assert 'invalid_ids' in result

    def test_valid_expansion(self):
        """Should expand from valid propositions."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.proposition_exists.return_value = True
            mock_db.get_proposition.return_value = {
                'id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight',
            }
            mock_db.get_proposition_neighbors.return_value = {
                'propositions': [],
                'relationships': [],
            }
            mock_db.get_evidence.return_value = []

            result = expand_argument_map('test_project', ['a'])

        assert result['success'] is True
        assert result['origin_propositions'] == ['a']
        assert len(result['subgraph']['propositions']) == 1


class TestEmbedPropositions:
    """Tests for embed_propositions MCP tool."""

    def test_no_propositions(self):
        """Should handle empty project gracefully."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_project_propositions.return_value = []

            result = embed_propositions('empty_project')

        assert result['success'] is True
        assert result['embedded'] == 0

    def test_all_already_embedded(self):
        """Should skip already-embedded propositions."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_project_propositions.return_value = [
                {'id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight', 'evidence_count': 1},
            ]

            with patch('litrev_mcp.tools.argument_map_search.get_connection') as mock_conn:
                mock_conn.return_value.execute.return_value.fetchone.return_value = ('A: Def A',)

                result = embed_propositions('test_project')

        assert result['success'] is True
        assert result['embedded'] == 0
        assert result['skipped'] == 1

    def test_embeds_new_propositions(self):
        """Should embed propositions that are not yet embedded."""
        with patch('litrev_mcp.tools.argument_map_search.db') as mock_db:
            mock_db.init_concept_map_schema.return_value = None
            mock_db.get_project_propositions.return_value = [
                {'id': 'a', 'name': 'A', 'definition': 'Def A', 'source': 'insight', 'evidence_count': 0},
            ]

            with patch('litrev_mcp.tools.argument_map_search.get_connection') as mock_conn:
                mock_conn.return_value.execute.return_value.fetchone.return_value = None  # not embedded

                with patch('litrev_mcp.tools.argument_map_search.embed_texts') as mock_embed:
                    mock_embed.return_value = [[0.1] * 1536]

                    with patch('litrev_mcp.tools.argument_map_search.checkpoint'):
                        result = embed_propositions('test_project')

        assert result['success'] is True
        assert result['embedded'] == 1
        mock_db.upsert_proposition_embedding.assert_called_once()
