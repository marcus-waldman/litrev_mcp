"""
Project context operations for tailoring responses.

Manages _context.md files that store project-level context (goal, audience, style)
for tailoring Claude's responses during literature review.
"""

from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from litrev_mcp.config import config_manager


CONTEXT_FILENAME = "_context.md"

CONTEXT_TEMPLATE = '''# {name} Context

## Goal
[What is this literature review trying to accomplish?]

## Audience
[Who will read/use this work? What's their background?]

## Style
[Writing style, tone, format preferences]

## Key Questions
[Core questions driving the review]

## Notes
[Additional context, constraints, or evolution notes]

---
*Last updated: {date}*
'''


def get_context_path(project: str) -> Optional[Path]:
    """Get path to project's _context.md file."""
    lit_path = config_manager.literature_path
    if not lit_path:
        return None
    return lit_path / project / CONTEXT_FILENAME


async def get_project_context(project: str) -> dict[str, Any]:
    """
    Read project context from _context.md file.

    Args:
        project: Project code (e.g., 'MI-IC')

    Returns:
        Dictionary with:
        - success: bool
        - exists: bool - whether context file exists
        - context: str | None - full markdown content if exists
        - path: str - path to context file
        - template: str - template content if file doesn't exist
    """
    context_path = get_context_path(project)

    if not context_path:
        return {
            'success': False,
            'error': {
                'code': 'NO_LITERATURE_PATH',
                'message': 'Literature path not configured. Run setup_check first.'
            }
        }

    if not context_path.exists():
        return {
            'success': True,
            'exists': False,
            'context': None,
            'path': str(context_path),
            'template': CONTEXT_TEMPLATE.format(
                name=project,
                date=datetime.now().strftime('%Y-%m-%d')
            )
        }

    return {
        'success': True,
        'exists': True,
        'context': context_path.read_text(encoding='utf-8'),
        'path': str(context_path)
    }


async def update_project_context(project: str, content: str) -> dict[str, Any]:
    """
    Create or update project context file.

    Args:
        project: Project code (e.g., 'MI-IC')
        content: Full markdown content for _context.md

    Returns:
        Dictionary with success status, path, and message
    """
    context_path = get_context_path(project)

    if not context_path:
        return {
            'success': False,
            'error': {
                'code': 'NO_LITERATURE_PATH',
                'message': 'Literature path not configured. Run setup_check first.'
            }
        }

    # Ensure project directory exists
    context_path.parent.mkdir(parents=True, exist_ok=True)

    # Write content
    context_path.write_text(content, encoding='utf-8')

    return {
        'success': True,
        'path': str(context_path),
        'message': f'Context saved to {CONTEXT_FILENAME}'
    }


def get_context_text(project: str) -> Optional[str]:
    """
    Helper: Get raw context text for injection into prompts.

    This is a synchronous helper for use in other tools that need
    to inject project context into their responses.

    Args:
        project: Project code

    Returns:
        Context markdown text if file exists, None otherwise
    """
    context_path = get_context_path(project)
    if context_path and context_path.exists():
        return context_path.read_text(encoding='utf-8')
    return None
