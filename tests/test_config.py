"""Basic tests for litrev-mcp."""

import pytest
from litrev_mcp.config import Config, ProjectConfig, ConfigManager


class TestConfig:
    """Tests for configuration models."""
    
    def test_default_config(self):
        """Test that default config is valid."""
        config = Config()
        assert config.projects == {}
        assert config.status_tags.needs_pdf == "_needs-pdf"
        assert config.status_tags.needs_notebooklm == "_needs-notebooklm"
        assert config.status_tags.complete == "_complete"
    
    def test_project_config(self):
        """Test project configuration."""
        project = ProjectConfig(
            name="Test Project",
            zotero_collection_key="ABC123",
            drive_folder="Literature/TEST"
        )
        assert project.name == "Test Project"
        assert project.zotero_collection_key == "ABC123"
        assert project.drive_folder == "Literature/TEST"
    
    def test_config_with_projects(self):
        """Test config with projects defined."""
        config = Config(
            projects={
                "TEST": ProjectConfig(
                    name="Test Project",
                    drive_folder="Literature/TEST"
                )
            }
        )
        assert "TEST" in config.projects
        assert config.projects["TEST"].name == "Test Project"


class TestConfigManager:
    """Tests for ConfigManager."""
    
    def test_config_manager_init(self):
        """Test ConfigManager initialization."""
        manager = ConfigManager()
        assert manager._config is None
        assert manager._drive_path is None
    
    def test_load_default_config(self):
        """Test loading default config when no file exists."""
        manager = ConfigManager()
        # Force drive_path to None so config_path is None
        manager._drive_path = None
        config = manager.load()
        assert isinstance(config, Config)
        assert config.projects == {}
