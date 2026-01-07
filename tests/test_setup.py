"""
Tests for setup wizard tools.

Tests for setup_check and setup_create_project.
"""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from litrev_mcp.tools.setup import (
    setup_check,
    setup_create_project,
)
from litrev_mcp.config import Config, ProjectConfig


class TestSetupCheck:
    """Tests for setup_check function."""

    @pytest.mark.asyncio
    async def test_setup_check_all_configured(self):
        """Test when everything is properly configured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                with patch('litrev_mcp.tools.setup.get_zotero_api_key') as mock_key:
                    with patch('litrev_mcp.tools.setup.get_zotero_user_id') as mock_user:
                        # Setup paths
                        drive_path = Path(tmpdir) / "GoogleDrive"
                        lit_path = drive_path / "Literature"
                        config_path = lit_path / ".litrev" / "config.yaml"

                        drive_path.mkdir()
                        lit_path.mkdir()
                        config_path.parent.mkdir(parents=True)
                        config_path.write_text("projects: {}")

                        mock_config.drive_path = drive_path
                        mock_config.literature_path = lit_path
                        mock_config.config_path = config_path

                        # Setup config
                        config = Config(projects={'TEST': ProjectConfig(name='Test', drive_folder='Literature/TEST')})
                        mock_config.load.return_value = config

                        # Setup credentials
                        mock_key.return_value = 'test_key'
                        mock_user.return_value = '123456'

                        result = await setup_check()

                        assert result['success'] is True
                        assert result['status'] == 'ready'
                        assert 'All systems configured' in result['message']
                        assert len([i for i in result['issues'] if i['severity'] == 'error']) == 0

    @pytest.mark.asyncio
    async def test_setup_check_missing_drive(self):
        """Test when Google Drive is not detected."""
        with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
            with patch('litrev_mcp.tools.setup.get_zotero_api_key') as mock_key:
                with patch('litrev_mcp.tools.setup.get_zotero_user_id') as mock_user:
                    mock_config.drive_path = None
                    mock_config.literature_path = None
                    mock_config.config_path = None

                    mock_key.return_value = 'test_key'
                    mock_user.return_value = '123456'

                    result = await setup_check()

                    assert result['success'] is True
                    assert result['status'] == 'needs_setup'
                    assert any(i['component'] == 'Google Drive' for i in result['issues'])
                    assert any(i['severity'] == 'error' for i in result['issues'])

    @pytest.mark.asyncio
    async def test_setup_check_missing_zotero_credentials(self):
        """Test when Zotero credentials are not set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                with patch('litrev_mcp.tools.setup.get_zotero_api_key') as mock_key:
                    with patch('litrev_mcp.tools.setup.get_zotero_user_id') as mock_user:
                        # Setup paths
                        drive_path = Path(tmpdir) / "GoogleDrive"
                        lit_path = drive_path / "Literature"
                        drive_path.mkdir()
                        lit_path.mkdir()

                        mock_config.drive_path = drive_path
                        mock_config.literature_path = lit_path
                        mock_config.config_path = None

                        # Missing credentials
                        mock_key.return_value = None
                        mock_user.return_value = None

                        result = await setup_check()

                        assert result['success'] is True
                        assert result['status'] == 'needs_setup'
                        assert any(i['component'] == 'Zotero' and 'API_KEY' in i['message'] for i in result['issues'])
                        assert any(i['component'] == 'Zotero' and 'USER_ID' in i['message'] for i in result['issues'])

    @pytest.mark.asyncio
    async def test_setup_check_with_warnings(self):
        """Test when system is functional but has warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                with patch('litrev_mcp.tools.setup.get_zotero_api_key') as mock_key:
                    with patch('litrev_mcp.tools.setup.get_zotero_user_id') as mock_user:
                        # Setup paths (without Literature folder)
                        drive_path = Path(tmpdir) / "GoogleDrive"
                        lit_path = drive_path / "Literature"
                        drive_path.mkdir()
                        # Note: NOT creating lit_path

                        mock_config.drive_path = drive_path
                        mock_config.literature_path = lit_path
                        mock_config.config_path = None

                        mock_key.return_value = 'test_key'
                        mock_user.return_value = '123456'

                        result = await setup_check()

                        assert result['success'] is True
                        # Should be ready_with_warnings since drive is there but lit folder missing
                        assert any(i['severity'] == 'warning' for i in result['issues'])


class TestSetupCreateProject:
    """Tests for setup_create_project function."""

    @pytest.mark.asyncio
    async def test_create_project_success(self):
        """Test successful project creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                # Setup paths
                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()

                mock_config.literature_path = lit_path
                mock_config.config_path = lit_path / ".litrev" / "config.yaml"

                # Setup empty config
                config = Config(projects={})
                mock_config.load.return_value = config

                result = await setup_create_project(
                    code="TEST",
                    name="Test Project",
                    zotero_collection_key="COL123",
                )

                assert result['success'] is True
                assert result['project']['code'] == 'TEST'
                assert result['project']['name'] == 'Test Project'

                # Verify directories were created
                project_dir = lit_path / "TEST"
                notes_dir = project_dir / "_notes"
                assert project_dir.exists()
                assert notes_dir.exists()

                # Verify config was saved
                mock_config.save.assert_called_once()
                saved_config = mock_config.save.call_args[0][0]
                assert 'TEST' in saved_config.projects
                assert saved_config.projects['TEST'].name == 'Test Project'
                assert saved_config.projects['TEST'].zotero_collection_key == 'COL123'

    @pytest.mark.asyncio
    async def test_create_project_without_zotero_key(self):
        """Test project creation without Zotero collection key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()

                mock_config.literature_path = lit_path
                mock_config.config_path = lit_path / ".litrev" / "config.yaml"

                config = Config(projects={})
                mock_config.load.return_value = config

                result = await setup_create_project(
                    code="TEST",
                    name="Test Project",
                )

                assert result['success'] is True
                assert 'Create a Zotero collection' in '\n'.join(result['next_steps'])

                # Verify config
                mock_config.save.assert_called_once()
                saved_config = mock_config.save.call_args[0][0]
                assert saved_config.projects['TEST'].zotero_collection_key is None

    @pytest.mark.asyncio
    async def test_create_project_already_exists(self):
        """Test creating a project that already exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()

                mock_config.literature_path = lit_path

                # Existing project
                config = Config(
                    projects={
                        'TEST': ProjectConfig(name='Existing', drive_folder='Literature/TEST')
                    }
                )
                mock_config.load.return_value = config

                result = await setup_create_project(
                    code="TEST",
                    name="New Project",
                )

                assert result['success'] is False
                assert result['error']['code'] == 'PROJECT_EXISTS'

    @pytest.mark.asyncio
    async def test_create_project_no_drive(self):
        """Test project creation when Google Drive is not configured."""
        with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
            mock_config.literature_path = None

            result = await setup_create_project(
                code="TEST",
                name="Test Project",
            )

            assert result['success'] is False
            assert result['error']['code'] == 'DRIVE_NOT_CONFIGURED'

    @pytest.mark.asyncio
    async def test_create_project_config_save_fails(self):
        """Test handling of config save failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('litrev_mcp.tools.setup.config_manager') as mock_config:
                lit_path = Path(tmpdir) / "Literature"
                lit_path.mkdir()

                mock_config.literature_path = lit_path

                config = Config(projects={})
                mock_config.load.return_value = config

                # Make save fail
                mock_config.save.side_effect = Exception("Save failed")

                result = await setup_create_project(
                    code="TEST",
                    name="Test Project",
                )

                assert result['success'] is False
                assert result['error']['code'] == 'CONFIG_SAVE_FAILED'
