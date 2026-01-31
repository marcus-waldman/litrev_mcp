"""
Setup wizard for litrev-mcp.

Helps users configure their environment and create projects.
"""

import os
from typing import Any, Optional
from pathlib import Path

from litrev_mcp.config import (
    config_manager,
    get_zotero_api_key,
    get_zotero_user_id,
    Config,
    ProjectConfig,
)


async def setup_check() -> dict[str, Any]:
    """
    Check if litrev-mcp is properly configured.

    Verifies:
    - Google Drive path detection
    - Literature folder existence
    - Config file
    - Zotero credentials

    Returns:
        Dictionary with configuration status and any issues found.
    """
    try:
        issues = []
        warnings = []
        all_good = True

        # Check Google Drive path
        drive_path = config_manager.drive_path
        if not drive_path:
            issues.append({
                'severity': 'error',
                'component': 'Google Drive',
                'message': 'Google Drive path not detected',
                'fix': 'Set LITREV_DRIVE_PATH environment variable or ensure Google Drive is mounted',
            })
            all_good = False
        elif not drive_path.exists():
            issues.append({
                'severity': 'error',
                'component': 'Google Drive',
                'message': f'Google Drive path does not exist: {drive_path}',
                'fix': 'Ensure Google Drive is mounted and syncing',
            })
            all_good = False

        # Check Literature folder
        lit_path = config_manager.literature_path
        if lit_path and not lit_path.exists():
            issues.append({
                'severity': 'warning',
                'component': 'Literature Folder',
                'message': f'Literature folder does not exist: {lit_path}',
                'fix': 'Create the Literature folder in your Google Drive',
            })
            warnings.append('Literature folder not found')
        elif not lit_path:
            issues.append({
                'severity': 'error',
                'component': 'Literature Folder',
                'message': 'Cannot determine Literature folder path',
                'fix': 'Ensure Google Drive is properly configured',
            })
            all_good = False

        # Check config file
        config_path = config_manager.config_path
        if config_path and not config_path.exists():
            issues.append({
                'severity': 'warning',
                'component': 'Config File',
                'message': f'Config file does not exist: {config_path}',
                'fix': 'Use setup_create_project to create your first project',
            })
            warnings.append('No config file found')
        elif config_path:
            # Check if config has projects
            config = config_manager.load()
            if not config.projects:
                issues.append({
                    'severity': 'info',
                    'component': 'Projects',
                    'message': 'No projects configured',
                    'fix': 'Use setup_create_project to create a project',
                })

        # Check Google Drive credentials (if PyDrive2 installed)
        try:
            from litrev_mcp.tools.gdrive import verify_drive_access, get_credentials_path

            creds_path = get_credentials_path()
            if creds_path:
                # Credentials file exists, verify they work
                verify_result = verify_drive_access()
                if not verify_result.get('success'):
                    issues.append({
                        'severity': 'error',
                        'component': 'Google Drive OAuth',
                        'message': f"Google Drive credentials invalid: {verify_result.get('error', 'Unknown error')}",
                        'fix': verify_result.get('suggestion', 'Run gdrive_reauthenticate to refresh credentials'),
                    })
                    all_good = False
        except ImportError:
            # PyDrive2 not installed, skip Drive check
            pass
        except Exception as e:
            issues.append({
                'severity': 'warning',
                'component': 'Google Drive OAuth',
                'message': f'Could not verify Google Drive credentials: {str(e)}',
                'fix': 'Run gdrive_reauthenticate if you encounter Drive errors',
            })
            warnings.append('Could not verify Google Drive credentials')

        # Check Zotero credentials
        zotero_key = get_zotero_api_key()
        zotero_user = get_zotero_user_id()

        if not zotero_key:
            issues.append({
                'severity': 'error',
                'component': 'Zotero',
                'message': 'ZOTERO_API_KEY not set',
                'fix': 'Set ZOTERO_API_KEY environment variable (get from https://www.zotero.org/settings/keys)',
            })
            all_good = False

        if not zotero_user:
            issues.append({
                'severity': 'error',
                'component': 'Zotero',
                'message': 'ZOTERO_USER_ID not set',
                'fix': 'Set ZOTERO_USER_ID environment variable (get from https://www.zotero.org/settings/keys)',
            })
            all_good = False

        # Check Mathpix credentials (optional)
        mathpix_id = os.environ.get("MATHPIX_APP_ID")
        mathpix_key = os.environ.get("MATHPIX_APP_KEY")

        # Determine overall status
        if all_good and not warnings:
            status = 'ready'
            message = 'All systems configured correctly!'
        elif all_good and warnings:
            status = 'ready_with_warnings'
            message = 'System is functional but has warnings'
        else:
            status = 'needs_setup'
            message = 'Configuration required'

        return {
            'success': True,
            'status': status,
            'message': message,
            'issues': issues,
            'paths': {
                'drive_path': str(drive_path) if drive_path else None,
                'literature_path': str(lit_path) if lit_path else None,
                'config_path': str(config_path) if config_path else None,
            },
            'credentials': {
                'zotero_api_key': 'set' if zotero_key else 'not set',
                'zotero_user_id': zotero_user if zotero_user else 'not set',
                'mathpix': 'set' if (mathpix_id and mathpix_key) else 'not set (optional)',
            },
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'SETUP_CHECK_ERROR',
                'message': str(e),
            }
        }


async def setup_create_project(
    code: str,
    name: str,
    zotero_collection_key: Optional[str] = None,
) -> dict[str, Any]:
    """
    Create a new literature review project.

    This will:
    1. Add project to config file
    2. Create project directory structure in Google Drive
    3. Create _notes subdirectory

    Args:
        code: Short project code (e.g., "MEAS-ERR")
        name: Full project name
        zotero_collection_key: Zotero collection key (optional, can add later)

    Returns:
        Dictionary with project creation status and paths.
    """
    try:
        # Validate environment
        lit_path = config_manager.literature_path
        if not lit_path:
            return {
                'success': False,
                'error': {
                    'code': 'DRIVE_NOT_CONFIGURED',
                    'message': 'Google Drive path not detected. Run setup_check for details.',
                }
            }

        # Load existing config
        config = config_manager.load()

        # Check if project already exists
        if code in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_EXISTS',
                    'message': f"Project '{code}' already exists",
                }
            }

        # Create project directory structure
        project_dir = lit_path / code
        notes_dir = project_dir / "_notes"
        inbox_dir = project_dir / "to_add"

        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            notes_dir.mkdir(parents=True, exist_ok=True)
            inbox_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return {
                'success': False,
                'error': {
                    'code': 'DIRECTORY_CREATION_FAILED',
                    'message': f"Failed to create project directories: {str(e)}",
                }
            }

        # Generate workflow templates if enabled
        templates_created = []
        if config.workflow.auto_generate_templates:
            from litrev_mcp.templates import (
                WORKFLOW_TEMPLATE,
                SYNTHESIS_NOTES_TEMPLATE,
                GAPS_TEMPLATE,
                PIVOTS_TEMPLATE,
                SEARCHES_TEMPLATE
            )

            template_files = {
                '_workflow.md': WORKFLOW_TEMPLATE,
                '_synthesis_notes.md': SYNTHESIS_NOTES_TEMPLATE,
                '_gaps.md': GAPS_TEMPLATE,
                '_pivots.md': PIVOTS_TEMPLATE,
                '_searches.md': SEARCHES_TEMPLATE
            }

            for filename, template in template_files.items():
                filepath = project_dir / filename
                if not filepath.exists():  # Don't overwrite if already exists
                    try:
                        filepath.write_text(template, encoding='utf-8')
                        templates_created.append(filename)
                    except Exception as e:
                        # Log warning but don't fail project creation
                        pass

        # Add project to config
        new_project = ProjectConfig(
            name=name,
            zotero_collection_key=zotero_collection_key,
            drive_folder=f"Literature/{code}",
            notebooklm_notebooks=[],
        )

        config.projects[code] = new_project

        # Save config
        try:
            config_manager.save(config)
        except Exception as e:
            return {
                'success': False,
                'error': {
                    'code': 'CONFIG_SAVE_FAILED',
                    'message': f"Failed to save config: {str(e)}",
                }
            }

        # Build instructions for next steps
        next_steps = []

        if not zotero_collection_key:
            next_steps.append("Create a Zotero collection for this project")
            next_steps.append("Add the collection key to config using zotero_list_projects to find the key")

        next_steps.append("Start adding papers with zotero_add_paper or search tools")

        if templates_created:
            next_steps.append("Review _workflow.md to understand the phase structure")
            next_steps.append("Document initial gaps in _gaps.md")

        next_steps.append("Create NotebookLM notebooks in Google Drive")

        return {
            'success': True,
            'project': {
                'code': code,
                'name': name,
                'path': str(project_dir),
                'notes_path': str(notes_dir),
            },
            'templates_created': templates_created,
            'message': f"Project '{code}' created successfully",
            'next_steps': next_steps,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'CREATE_PROJECT_ERROR',
                'message': str(e),
            }
        }
