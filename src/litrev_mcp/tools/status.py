"""
Project status and pending actions for litrev-mcp.

Provides dashboard views and actionable todo lists.
"""

from typing import Any, Optional
from datetime import datetime, timedelta

from litrev_mcp.config import config_manager
from litrev_mcp.tools.zotero import get_zotero_client, get_status_from_tags, item_to_dict
from litrev_mcp.tools.insights import get_notes_path
from litrev_mcp.tools.context import get_context_text
from litrev_mcp.tools.workflow import get_workflow_status


async def project_status(
    project: str,
) -> dict[str, Any]:
    """
    Get a dashboard view of a project.

    Args:
        project: Project code (e.g., "MEAS-ERR")

    Returns:
        Dictionary with comprehensive project status including papers,
        insights, and recent activity.
    """
    try:
        config = config_manager.load()

        # Validate project
        if project not in config.projects:
            return {
                'success': False,
                'error': {
                    'code': 'PROJECT_NOT_FOUND',
                    'message': f"Project '{project}' not found in config",
                }
            }

        proj_config = config.projects[project]
        collection_key = proj_config.zotero_collection_key

        # Get paper counts from Zotero
        summary = {
            'total': 0,
            'needs_pdf': 0,
            'needs_notebooklm': 0,
            'complete': 0,
            'untagged': 0,
        }

        recent_additions = []

        if collection_key:
            try:
                zot = get_zotero_client()
                items = zot.collection_items(collection_key, itemType='-attachment', limit=100)

                # Count by status
                for item in items:
                    summary['total'] += 1
                    status = get_status_from_tags(
                        item.get('data', {}).get('tags', []),
                        {
                            'needs_pdf': config.status_tags.needs_pdf,
                            'needs_notebooklm': config.status_tags.needs_notebooklm,
                            'complete': config.status_tags.complete,
                        }
                    )
                    if status:
                        summary[status] += 1
                    else:
                        summary['untagged'] += 1

                # Get recent additions (last 30 days)
                cutoff_date = datetime.now() - timedelta(days=30)
                recent_items = []

                for item in items:
                    item_data = item.get('data', {})
                    date_added = item_data.get('dateAdded', '')

                    if date_added:
                        try:
                            added_dt = datetime.fromisoformat(date_added.replace('Z', '+00:00'))
                            if added_dt >= cutoff_date:
                                item_dict = item_to_dict(item, config)
                                recent_items.append({
                                    'title': item_dict['title'],
                                    'authors': item_dict['authors'],
                                    'added': date_added[:10],  # Just the date part
                                    'status': item_dict['status'],
                                })
                        except (ValueError, TypeError):
                            pass

                # Sort by date added (newest first) and limit to 10
                recent_additions = sorted(recent_items, key=lambda x: x['added'], reverse=True)[:10]

            except Exception:
                # If Zotero fails, continue with empty data
                pass

        # Get insights stats
        insights_stats = {
            'total': 0,
            'by_source': {},
        }

        recent_insights = []

        notes_path = get_notes_path(project)
        if notes_path and notes_path.exists():
            from litrev_mcp.tools.insights import parse_insight_file

            all_insights = []
            for filepath in notes_path.glob('*.md'):
                insight = parse_insight_file(filepath)
                if insight:
                    insights_stats['total'] += 1
                    source = insight['frontmatter'].get('source', 'unknown')
                    insights_stats['by_source'][source] = insights_stats['by_source'].get(source, 0) + 1

                    all_insights.append({
                        'topic': insight['frontmatter'].get('topic', ''),
                        'source': source,
                        'date': str(insight['frontmatter'].get('date', '')),
                    })

            # Get recent insights (last 30 days)
            cutoff_date_str = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
            recent_insights = [
                ins for ins in all_insights
                if ins['date'] >= cutoff_date_str
            ]
            recent_insights = sorted(recent_insights, key=lambda x: x['date'], reverse=True)[:10]

        # Build drive folder path
        lit_path = config_manager.literature_path
        drive_folder = f"Literature/{project}" if lit_path else None

        # Get NotebookLM notebooks from config
        notebooklm_notebooks = proj_config.notebooklm_notebooks if hasattr(proj_config, 'notebooklm_notebooks') else []

        # Get workflow status if enabled
        workflow_metrics = None
        if config.workflow.phase_tracking:
            workflow_result = await get_workflow_status(project)
            if workflow_result['success']:
                workflow_metrics = workflow_result['workflow']

        result = {
            'success': True,
            'project': project,
            'name': proj_config.name,
            'context': get_context_text(project),
            'summary': summary,
            'insights': insights_stats,
            'recent_additions': recent_additions,
            'recent_insights': recent_insights,
            'drive_folder': drive_folder,
            'notebooklm_notebooks': notebooklm_notebooks,
            'workflow': workflow_metrics,
        }

        # Add proactive guidance
        if config.workflow.show_guidance:
            guidance_items = []

            # Suggest based on paper counts
            if summary['needs_pdf'] > 0:
                guidance_items.append(f"📄 {summary['needs_pdf']} papers need PDFs - acquire and update status")

            if summary['needs_notebooklm'] > 0:
                guidance_items.append(f"📝 {summary['needs_notebooklm']} papers ready for NotebookLM analysis")

            # Suggest based on workflow state
            if workflow_metrics:
                if workflow_metrics['gaps']['total'] == 0:
                    guidance_items.append("💡 Consider documenting research gaps in _gaps.md")

                open_gaps = workflow_metrics['gaps']['by_status'].get('not_found', 0)
                if open_gaps > 0:
                    guidance_items.append(f"🔍 {open_gaps} open gaps to address - review _gaps.md")

                if workflow_metrics['last_session']:
                    try:
                        last_session = datetime.strptime(workflow_metrics['last_session'], '%Y-%m-%d')
                        if datetime.now() - last_session > timedelta(days=7):
                            guidance_items.append("⏰ Over a week since last session - review _workflow.md to resume")
                    except (ValueError, TypeError):
                        pass

            result['guidance'] = {
                'current_status': workflow_metrics['current_phase'] if workflow_metrics else None,
                'recommendations': guidance_items
            }

        return result

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'STATUS_ERROR',
                'message': str(e),
            }
        }


async def pending_actions() -> dict[str, Any]:
    """
    Get all pending user actions across projects.

    Returns complete information for both Zotero and Google Drive operations.

    Returns:
        Dictionary with PDFs to acquire and papers to add to NotebookLM.
    """
    try:
        config = config_manager.load()
        lit_path = config_manager.literature_path

        pdfs_to_acquire = []
        papers_to_add_to_notebooklm = []

        # Check each project
        for project_code, proj_config in config.projects.items():
            collection_key = proj_config.zotero_collection_key

            if not collection_key:
                continue

            try:
                zot = get_zotero_client()
                items = zot.collection_items(collection_key, itemType='-attachment')

                for item in items:
                    item_data = item.get('data', {})
                    item_dict = item_to_dict(item, config)

                    # Check status
                    status = item_dict.get('status')

                    if status == 'needs_pdf':
                        # Get DOI for URL
                        doi = item_data.get('DOI', '')
                        doi_url = f"https://doi.org/{doi}" if doi else None

                        pdfs_to_acquire.append({
                            'project': project_code,
                            'citation_key': item_dict.get('citation_key'),
                            'title': item_dict.get('title'),
                            'authors': item_dict.get('authors'),
                            'year': item_dict.get('year'),
                            'doi': doi,
                            'doi_url': doi_url,
                            'item_key': item_dict.get('item_key'),
                            'zotero_item_title': item_dict.get('title'),
                            'drive_filename': item_dict.get('pdf_filename'),
                            'drive_folder': f"Literature/{project_code}/",
                        })

                    elif status == 'needs_notebooklm':
                        citation_key = item_dict.get('citation_key')
                        pdf_filename = item_dict.get('pdf_filename')

                        if citation_key and pdf_filename:
                            # Suggest notebook from config
                            suggested_notebook = None
                            if hasattr(proj_config, 'notebooklm_notebooks') and proj_config.notebooklm_notebooks:
                                suggested_notebook = proj_config.notebooklm_notebooks[0]

                            papers_to_add_to_notebooklm.append({
                                'project': project_code,
                                'citation_key': citation_key,
                                'title': item_dict.get('title'),
                                'drive_filename': pdf_filename,
                                'drive_folder': f"Literature/{project_code}/",
                                'drive_full_path': f"Literature/{project_code}/{pdf_filename}",
                                'suggested_notebook': suggested_notebook,
                            })

            except Exception:
                # Skip projects that fail
                continue

        return {
            'success': True,
            'pdfs_to_acquire': pdfs_to_acquire,
            'papers_to_add_to_notebooklm': papers_to_add_to_notebooklm,
        }

    except Exception as e:
        return {
            'success': False,
            'error': {
                'code': 'PENDING_ACTIONS_ERROR',
                'message': str(e),
            }
        }
