"""
Google Drive integration for litrev-mcp.

Provides authentication and file operations for Google Drive,
enabling automatic linking of PDFs to Zotero entries.
"""

import os
from pathlib import Path
from typing import Any, Optional

from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

from litrev_mcp.config import config_manager


# Global drive instance (authenticated once per session)
_drive: Optional[GoogleDrive] = None
_gauth: Optional[GoogleAuth] = None


def get_credentials_path() -> Optional[Path]:
    """Get path to credentials.json file."""
    config_path = config_manager.config_path
    if config_path:
        creds_path = config_path.parent / "credentials.json"
        if creds_path.exists():
            return creds_path
    return None


def get_token_path() -> Path:
    """Get path to store token.json (machine-specific, not synced)."""
    # Store in user's home directory under .litrev-mcp
    token_dir = Path.home() / ".litrev-mcp"
    token_dir.mkdir(parents=True, exist_ok=True)
    return token_dir / "token.json"


def authenticate() -> GoogleDrive:
    """
    Authenticate with Google Drive.

    Uses credentials.json from .litrev folder.
    Stores tokens in ~/.litrev-mcp/token.json (machine-specific).

    Returns:
        Authenticated GoogleDrive instance

    Raises:
        FileNotFoundError: If credentials.json not found
        Exception: If authentication fails
    """
    global _drive, _gauth

    if _drive is not None:
        return _drive

    creds_path = get_credentials_path()
    if not creds_path:
        raise FileNotFoundError(
            "credentials.json not found in .litrev folder. "
            "Please set up Google Cloud OAuth credentials."
        )

    token_path = get_token_path()

    # Configure PyDrive2 settings
    settings = {
        "client_config_backend": "file",
        "client_config_file": str(creds_path),
        "save_credentials": True,
        "save_credentials_backend": "file",
        "save_credentials_file": str(token_path),
        "get_refresh_token": True,
    }

    _gauth = GoogleAuth(settings=settings)

    # Try to load saved credentials
    if token_path.exists():
        _gauth.LoadCredentialsFile(str(token_path))

    if _gauth.credentials is None:
        # No saved credentials - need to authenticate
        _gauth.LocalWebserverAuth()
    elif _gauth.access_token_expired:
        # Refresh expired token
        _gauth.Refresh()
    else:
        # Valid credentials loaded
        _gauth.Authorize()

    # Save credentials for next time
    _gauth.SaveCredentialsFile(str(token_path))

    _drive = GoogleDrive(_gauth)
    return _drive


def find_file_by_name(filename: str, parent_folder_id: Optional[str] = None) -> Optional[dict]:
    """
    Find a file in Google Drive by name.

    Args:
        filename: Name of the file to find
        parent_folder_id: Optional parent folder ID to search within

    Returns:
        File metadata dict or None if not found
    """
    drive = authenticate()

    query = f"title = '{filename}' and trashed = false"
    if parent_folder_id:
        query += f" and '{parent_folder_id}' in parents"

    file_list = drive.ListFile({'q': query}).GetList()

    if file_list:
        return file_list[0]
    return None


def find_folder_by_path(folder_path: str) -> Optional[str]:
    """
    Find a folder ID by its path (e.g., "Literature/TEST").

    Args:
        folder_path: Path relative to Drive root (e.g., "Literature/TEST")

    Returns:
        Folder ID or None if not found
    """
    drive = authenticate()

    parts = folder_path.strip("/").split("/")
    current_parent = "root"

    for part in parts:
        query = f"title = '{part}' and '{current_parent}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        file_list = drive.ListFile({'q': query}).GetList()

        if not file_list:
            return None

        current_parent = file_list[0]['id']

    return current_parent


def get_file_in_folder(filename: str, folder_path: str) -> Optional[dict]:
    """
    Get a file by name within a specific folder path.

    Args:
        filename: Name of the file
        folder_path: Path to the folder (e.g., "Literature/TEST")

    Returns:
        File metadata dict or None if not found
    """
    folder_id = find_folder_by_path(folder_path)
    if not folder_id:
        return None

    return find_file_by_name(filename, folder_id)


def get_shareable_link(file_id: str) -> str:
    """
    Get or create a shareable link for a file.

    Sets the file to be viewable by anyone with the link.

    Args:
        file_id: Google Drive file ID

    Returns:
        Shareable URL for the file
    """
    drive = authenticate()

    file = drive.CreateFile({'id': file_id})
    file.FetchMetadata(fields='webViewLink,alternateLink')

    # Make file viewable by anyone with link
    try:
        file.InsertPermission({
            'type': 'anyone',
            'value': 'anyone',
            'role': 'reader'
        })
    except Exception:
        # Permission might already exist
        pass

    # Return the web view link
    return file.get('webViewLink') or file.get('alternateLink', '')


def get_drive_link_for_pdf(filename: str, project_code: str) -> Optional[str]:
    """
    Get a shareable Google Drive link for a PDF in a project folder.

    Args:
        filename: Name of the PDF file (e.g., "smith_glucose_2020.pdf")
        project_code: Project code (e.g., "TEST")

    Returns:
        Shareable URL or None if file not found
    """
    # Construct the folder path
    folder_path = f"Literature/{project_code}"

    # Find the file
    file_info = get_file_in_folder(filename, folder_path)
    if not file_info:
        return None

    # Get shareable link
    return get_shareable_link(file_info['id'])


async def add_link_attachment_to_zotero(
    zot,
    item_key: str,
    url: str,
    title: str = "Google Drive PDF"
) -> dict[str, Any]:
    """
    Add a linked URL attachment to a Zotero item.

    Args:
        zot: Pyzotero Zotero instance
        item_key: Key of the parent item
        url: URL to link
        title: Title for the attachment

    Returns:
        Result dict with success status
    """
    try:
        attachment = {
            'itemType': 'attachment',
            'parentItem': item_key,
            'linkMode': 'linked_url',
            'title': title,
            'url': url,
            'contentType': 'application/pdf',
            'tags': [],
            'relations': {},
        }

        result = zot.create_items([attachment])

        if result.get('successful'):
            return {
                'success': True,
                'message': f'Added Drive link to Zotero item {item_key}',
            }
        else:
            return {
                'success': False,
                'error': result.get('failed', 'Unknown error'),
            }

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }
