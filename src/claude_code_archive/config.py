"""Configuration management for Claude Code archive."""

import json
from pathlib import Path
from typing import Optional

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "claude-code-archive"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"
DEFAULT_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def get_default_archive_dir() -> Path:
    """Get the default archive directory."""
    return Path.home() / "Development" / "claude-code-archive" / "archive"


class Config:
    """Configuration for claude-code-archive."""

    def __init__(
        self,
        archive_dir: Optional[Path] = None,
        projects_dir: Optional[Path] = None,
    ):
        self.archive_dir = archive_dir or get_default_archive_dir()
        self.projects_dir = projects_dir or DEFAULT_CLAUDE_PROJECTS_DIR

    @property
    def db_path(self) -> Path:
        return self.archive_dir / "sessions.db"

    @property
    def toml_dir(self) -> Path:
        return self.archive_dir / "transcripts"

    def ensure_dirs(self):
        """Ensure archive directories exist."""
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from file."""
        path = config_path or DEFAULT_CONFIG_FILE

        if not path.exists():
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                archive_dir=Path(data["archive_dir"]) if data.get("archive_dir") else None,
                projects_dir=Path(data["projects_dir"]) if data.get("projects_dir") else None,
            )
        except (json.JSONDecodeError, KeyError):
            return cls()

    def save(self, config_path: Optional[Path] = None):
        """Save configuration to file."""
        path = config_path or DEFAULT_CONFIG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "archive_dir": str(self.archive_dir),
            "projects_dir": str(self.projects_dir),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
