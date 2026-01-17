"""Workflow tracking and best practices guidance tools."""
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Optional

from litrev_mcp.config import config_manager


async def save_gap(
    project: str,
    topic: str,
    why_matters: str,
    search_strategy: str,
    status: str = "searched"
) -> dict[str, Any]:
    """
    Document a gap - something you're searching for.

    Args:
        project: Project code
        topic: Concise description of the gap
        why_matters: Why this gap is important
        search_strategy: Search queries/approaches tried
        status: searched | partially_found | not_found

    Returns:
        dict with success status and gap details
    """
    try:
        config = config_manager.load()
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f'Project {project} not found'
                }
            }

        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'NO_DRIVE_PATH',
                    'message': 'Google Drive path not found'
                }
            }

        gaps_path = lit_path / project / "_gaps.md"

        # Create file if doesn't exist
        if not gaps_path.exists():
            from litrev_mcp.templates import GAPS_TEMPLATE
            gaps_path.write_text(GAPS_TEMPLATE, encoding='utf-8')

        # Append gap entry
        today = datetime.now().strftime('%Y-%m-%d')
        gap_entry = f"""
### Gap: {topic}
- **Status**: {status}
- **Why it matters**: {why_matters}
- **Search strategy**: {search_strategy}
- **Date opened**: {today}
- **Last updated**: {today}

---

"""

        content = gaps_path.read_text(encoding='utf-8')
        gaps_path.write_text(content + gap_entry, encoding='utf-8')

        return {
            'success': True,
            'message': f'Gap "{topic}" saved to {project}/_gaps.md',
            'gap': {
                'topic': topic,
                'status': status,
                'file': str(gaps_path)
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SAVE_FAILED',
                'message': str(e)
            }
        }


async def save_session_log(
    project: str,
    status: str,
    completed: list[str],
    pivots: Optional[list[str]] = None,
    questions: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
    blocked: Optional[str] = None
) -> dict[str, Any]:
    """
    Log end-of-session summary.

    Args:
        project: Project code
        status: Overall status (e.g., "Phase 2 in progress")
        completed: List of accomplishments this session
        pivots: List of conceptual shifts documented
        questions: Active questions needing answers
        next_steps: Next actions to take
        blocked: What's blocking progress, if anything

    Returns:
        dict with success status and session details
    """
    try:
        config = config_manager.load()
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f'Project {project} not found'
                }
            }

        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'NO_DRIVE_PATH',
                    'message': 'Google Drive path not found'
                }
            }

        workflow_path = lit_path / project / "_workflow.md"

        if not workflow_path.exists():
            from litrev_mcp.templates import WORKFLOW_TEMPLATE
            workflow_path.write_text(WORKFLOW_TEMPLATE, encoding='utf-8')

        # Build session log entry
        today = datetime.now().strftime('%Y-%m-%d')
        log_entry = f"""
### Session {today}
**Status**: {status}

**Completed**:
"""
        for item in completed:
            log_entry += f"- ✓ {item}\n"

        if pivots:
            log_entry += "\n**Conceptual shifts documented**:\n"
            for pivot in pivots:
                log_entry += f"- **PIVOT**: {pivot}\n"

        if questions:
            log_entry += "\n**Active questions**:\n"
            for q in questions:
                log_entry += f"- {q}\n"

        if next_steps:
            log_entry += "\n**Next steps**:\n"
            for step in next_steps:
                log_entry += f"- [ ] {step}\n"

        if blocked:
            log_entry += f"\n**Blocked**: {blocked}\n"

        log_entry += "\n---\n"

        # Append to workflow file
        content = workflow_path.read_text(encoding='utf-8')
        workflow_path.write_text(content + log_entry, encoding='utf-8')

        return {
            'success': True,
            'message': f'Session log saved to {project}/_workflow.md',
            'session': {
                'date': today,
                'status': status,
                'completed_count': len(completed)
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SAVE_FAILED',
                'message': str(e)
            }
        }


async def save_pivot(
    project: str,
    topic: str,
    before: str,
    after: str,
    rationale: str,
    source: Optional[str] = None,
    impact: Optional[str] = None
) -> dict[str, Any]:
    """
    Document a conceptual pivot - when understanding shifts.

    Args:
        project: Project code
        topic: Concise description of the pivot
        before: What you thought before
        after: What you learned
        rationale: Why this matters
        source: Citation or insight that caused shift
        impact: How this changes the manuscript

    Returns:
        dict with success status and pivot details
    """
    try:
        config = config_manager.load()
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f'Project {project} not found'
                }
            }

        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'NO_DRIVE_PATH',
                    'message': 'Google Drive path not found'
                }
            }

        pivots_path = lit_path / project / "_pivots.md"

        if not pivots_path.exists():
            from litrev_mcp.templates import PIVOTS_TEMPLATE
            pivots_path.write_text(PIVOTS_TEMPLATE, encoding='utf-8')

        # Build pivot entry
        today = datetime.now().strftime('%Y-%m-%d')
        pivot_entry = f"""
### Pivot: {topic}
**Date**: {today}

**What we thought before**: {before}

**What we learned**: {after}

**Rationale for change**: {rationale}
"""

        if source:
            pivot_entry += f"- Source: {source}\n"
        if impact:
            pivot_entry += f"- Impact on manuscript: {impact}\n"

        pivot_entry += "\n---\n"

        # Append to pivots file
        content = pivots_path.read_text(encoding='utf-8')
        pivots_path.write_text(content + pivot_entry, encoding='utf-8')

        return {
            'success': True,
            'message': f'Pivot "{topic}" saved to {project}/_pivots.md',
            'pivot': {
                'topic': topic,
                'date': today,
                'file': str(pivots_path)
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SAVE_FAILED',
                'message': str(e)
            }
        }


async def save_search_strategy(
    project: str,
    goal: str,
    queries: list[dict[str, str]],
    conclusion: str
) -> dict[str, Any]:
    """
    Record search strategy for reproducibility.

    Args:
        project: Project code
        goal: What gap you're trying to fill
        queries: List of dicts with 'query', 'database', 'result' keys
        conclusion: What you found or confirmed not finding

    Returns:
        dict with success status and search details
    """
    try:
        config = config_manager.load()
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f'Project {project} not found'
                }
            }

        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'NO_DRIVE_PATH',
                    'message': 'Google Drive path not found'
                }
            }

        searches_path = lit_path / project / "_searches.md"

        if not searches_path.exists():
            from litrev_mcp.templates import SEARCHES_TEMPLATE
            searches_path.write_text(SEARCHES_TEMPLATE, encoding='utf-8')

        # Build search entry
        today = datetime.now().strftime('%Y-%m-%d')
        search_entry = f"""
### Search: {goal}
**Date**: {today}

"""

        for i, query_info in enumerate(queries, 1):
            search_entry += f"**Query {i}**: {query_info['query']}\n"
            search_entry += f"- Database: {query_info.get('database', 'Not specified')}\n"
            search_entry += f"- Result: {query_info['result']}\n\n"

        search_entry += f"**Conclusion**: {conclusion}\n\n---\n"

        # Append to searches file
        content = searches_path.read_text(encoding='utf-8')
        searches_path.write_text(content + search_entry, encoding='utf-8')

        return {
            'success': True,
            'message': f'Search strategy saved to {project}/_searches.md',
            'search': {
                'goal': goal,
                'date': today,
                'query_count': len(queries)
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SAVE_FAILED',
                'message': str(e)
            }
        }


async def get_workflow_status(project: str) -> dict[str, Any]:
    """
    Get workflow metrics for a project.

    Returns counts of gaps, pivots, searches, and recent session info.

    Args:
        project: Project code

    Returns:
        dict with success status and workflow metrics
    """
    try:
        config = config_manager.load()
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f'Project {project} not found'
                }
            }

        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'NO_DRIVE_PATH',
                    'message': 'Google Drive path not found'
                }
            }

        project_path = lit_path / project

        # Count workflow elements
        gaps_count = 0
        gaps_by_status = {'searched': 0, 'partially_found': 0, 'not_found': 0}
        pivots_count = 0
        searches_count = 0
        last_session_date = None
        current_phase = None

        # Parse _gaps.md
        gaps_path = project_path / "_gaps.md"
        if gaps_path.exists():
            content = gaps_path.read_text(encoding='utf-8')
            gaps_count = content.count('### Gap:')
            for status in ['searched', 'partially_found', 'not_found']:
                gaps_by_status[status] = content.count(f'**Status**: {status}')

        # Parse _pivots.md
        pivots_path = project_path / "_pivots.md"
        if pivots_path.exists():
            content = pivots_path.read_text(encoding='utf-8')
            pivots_count = content.count('### Pivot:')

        # Parse _searches.md
        searches_path = project_path / "_searches.md"
        if searches_path.exists():
            content = searches_path.read_text(encoding='utf-8')
            searches_count = content.count('### Search:')

        # Parse _workflow.md for last session and phase
        workflow_path = project_path / "_workflow.md"
        if workflow_path.exists():
            content = workflow_path.read_text(encoding='utf-8')

            # Find last session
            sessions = re.findall(r'### Session (\d{4}-\d{2}-\d{2})', content)
            if sessions:
                last_session_date = sessions[-1]

            # Find current phase status
            phase_matches = re.findall(r'## Phase \d+:.*?\*\*Status\*\*: (\w+)', content, re.DOTALL)
            if phase_matches:
                # Find first non-complete phase
                for i, phase_status in enumerate(phase_matches, 1):
                    if phase_status != 'complete':
                        current_phase = f'Phase {i}'
                        break
                if not current_phase:
                    current_phase = 'All phases complete'

        return {
            'success': True,
            'project': project,
            'workflow': {
                'gaps': {
                    'total': gaps_count,
                    'by_status': gaps_by_status
                },
                'pivots': pivots_count,
                'searches': searches_count,
                'last_session': last_session_date,
                'current_phase': current_phase or 'Not started'
            }
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'QUERY_FAILED',
                'message': str(e)
            }
        }
