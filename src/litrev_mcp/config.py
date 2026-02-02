"""
Configuration management for litrev-mcp.

Handles:
- Google Drive path detection across platforms
- Config file loading from Literature/.litrev/config.yaml
- Environment variable reading for API keys
"""

import os
import platform
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """Configuration for a single literature review project."""
    name: str
    zotero_collection_key: Optional[str] = None
    drive_folder: str
    notebooklm_notebooks: list[str] = Field(default_factory=list)


class StatusTags(BaseModel):
    """Zotero tags used to track paper status."""
    needs_pdf: str = "_needs-pdf"
    needs_notebooklm: str = "_needs-notebooklm"
    complete: str = "_complete"


class BetterBibTexConfig(BaseModel):
    """Better BibTeX configuration."""
    citation_key_pattern: str = "[auth:lower]_[shorttitle3_3:lower]_[year]"


class RAGConfig(BaseModel):
    """RAG (Retrieval Augmented Generation) configuration."""
    embedding_dimensions: int = Field(
        default=1536,
        ge=256,
        le=1536,
        description="Embedding vector dimensions. OpenAI text-embedding-3-small supports 256-1536. "
                    "Lower = smaller storage, slightly less accuracy. Default 1536 (6KB/chunk), "
                    "512 recommended for large collections (2KB/chunk, ~5% accuracy loss)."
    )


class WorkflowConfig(BaseModel):
    """Configuration for workflow guidance and best practices."""
    enabled: bool = True
    show_guidance: bool = True
    phase_tracking: bool = True
    auto_generate_templates: bool = True


class ArgumentMapConfig(BaseModel):
    """Configuration for argument map feature."""
    enabled: bool = True
    auto_extract: bool = True
    show_scaffolding: bool = True


class DatabaseConfig(BaseModel):
    """Configuration for MotherDuck cloud database."""
    motherduck_database: str = "litrev"


class Config(BaseModel):
    """Main configuration model."""
    projects: dict[str, ProjectConfig] = Field(default_factory=dict)
    status_tags: StatusTags = Field(default_factory=StatusTags)
    notebooklm_pattern: str = "{project_code} - {type} - {descriptor}"
    better_bibtex: BetterBibTexConfig = Field(default_factory=BetterBibTexConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    workflow: WorkflowConfig = Field(default_factory=WorkflowConfig)
    argument_map: ArgumentMapConfig = Field(default_factory=ArgumentMapConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)


class ConfigManager:
    """Manages configuration loading and access."""
    
    def __init__(self):
        self._config: Optional[Config] = None
        self._drive_path: Optional[Path] = None
        self._config_path: Optional[Path] = None
    
    @property
    def drive_path(self) -> Optional[Path]:
        """Get the detected Google Drive path."""
        if self._drive_path is None:
            self._drive_path = detect_google_drive_path()
        return self._drive_path
    
    @property
    def literature_path(self) -> Optional[Path]:
        """Get the Literature folder path."""
        if self.drive_path is None:
            return None
        return self.drive_path / "Literature"
    
    @property
    def config_path(self) -> Optional[Path]:
        """Get the config file path."""
        if self.literature_path is None:
            return None
        return self.literature_path / ".litrev" / "config.yaml"
    
    def load(self) -> Config:
        """Load configuration from file, or return defaults."""
        if self._config is not None:
            return self._config
        
        if self.config_path and self.config_path.exists():
            with open(self.config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
            self._config = Config(**data)
        else:
            self._config = Config()
        
        return self._config
    
    def save(self, config: Config) -> None:
        """Save configuration to file."""
        if self.config_path is None:
            raise ValueError("Cannot save config: Google Drive path not detected")
        
        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_path, 'w') as f:
            yaml.dump(config.model_dump(), f, default_flow_style=False, sort_keys=False)
        
        self._config = config
    
    @property
    def config(self) -> Config:
        """Get the current configuration (loads if needed)."""
        return self.load()


def detect_google_drive_path() -> Optional[Path]:
    """
    Detect the Google Drive path based on the current platform.
    
    Returns None if Google Drive is not found.
    
    Checks:
    - LITREV_DRIVE_PATH environment variable (override)
    - macOS: ~/Library/CloudStorage/GoogleDrive-*/My Drive
    - Linux: ~/google-drive or similar
    - Windows: G:\\My Drive or similar
    """
    # Check for environment variable override
    env_path = os.environ.get("LITREV_DRIVE_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    
    system = platform.system()
    
    if system == "Darwin":  # macOS
        return _detect_macos_drive()
    elif system == "Linux":
        return _detect_linux_drive()
    elif system == "Windows":
        return _detect_windows_drive()
    
    return None


def _detect_macos_drive() -> Optional[Path]:
    """Detect Google Drive on macOS."""
    cloud_storage = Path.home() / "Library" / "CloudStorage"
    
    if not cloud_storage.exists():
        return None
    
    # Look for GoogleDrive-* folders
    for item in cloud_storage.iterdir():
        if item.is_dir() and item.name.startswith("GoogleDrive-"):
            my_drive = item / "My Drive"
            if my_drive.exists():
                return my_drive
    
    return None


def _detect_linux_drive() -> Optional[Path]:
    """Detect Google Drive on Linux."""
    # Common locations for Google Drive on Linux
    candidates = [
        Path.home() / "google-drive",
        Path.home() / "Google Drive",
        Path.home() / "GoogleDrive",
        Path.home() / ".google-drive",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


def _detect_windows_drive() -> Optional[Path]:
    """Detect Google Drive on Windows."""
    # Common locations for Google Drive on Windows
    candidates = [
        Path("G:/My Drive"),
        Path("G:/MyDrive"),
        Path.home() / "Google Drive",
        Path.home() / "GoogleDrive",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


def get_env_var(name: str, required: bool = False) -> Optional[str]:
    """Get an environment variable, optionally raising if missing."""
    value = os.environ.get(name)
    if required and not value:
        raise ValueError(f"Required environment variable {name} is not set")
    return value


def get_zotero_api_key() -> Optional[str]:
    """Get the Zotero API key from environment."""
    return get_env_var("ZOTERO_API_KEY")


def get_zotero_user_id() -> Optional[str]:
    """Get the Zotero user ID from environment."""
    return get_env_var("ZOTERO_USER_ID")


def get_ncbi_api_key() -> Optional[str]:
    """Get the NCBI API key from environment (optional)."""
    return get_env_var("NCBI_API_KEY")


def get_semantic_scholar_api_key() -> Optional[str]:
    """Get the Semantic Scholar API key from environment (optional)."""
    return get_env_var("SEMANTIC_SCHOLAR_API_KEY") or get_env_var("SEMANTICSCHOLAR_API")


def get_motherduck_token() -> Optional[str]:
    """Get the MotherDuck token from environment (required for database access)."""
    return get_env_var("MOTHERDUCK_TOKEN")


# Global config manager instance
config_manager = ConfigManager()
