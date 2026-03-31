"""
Shared State Manager — persistent JSON-based state and history.

Manages a single JSON file for current state and an append-only
JSONL file for history entries.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class SharedStateManager:
    """Manages persistent shared state as JSON files.

    Parameters:
        state_path: path to the JSON state file.
        history_path: path to the JSONL history file (optional).
    """

    def __init__(self, state_path: str,
                 history_path: str | None = None):
        self.state_path = Path(state_path)
        self.history_path = Path(history_path) if history_path else None

    def load(self) -> dict[str, Any]:
        """Load state from JSON file. Returns empty dict if not found."""
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def save(self, state: dict[str, Any]) -> None:
        """Save state dict to JSON file, adding a timestamp."""
        state["_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def update(self, **kwargs: Any) -> dict[str, Any]:
        """Load, merge kwargs, save, and return the updated state."""
        state = self.load()
        state.update(kwargs)
        self.save(state)
        return state

    def append_history(self, entry: dict[str, Any]) -> None:
        """Append an entry to the history JSONL file."""
        if not self.history_path:
            return
        entry["_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def read_history(self, limit: int = 0) -> list[dict[str, Any]]:
        """Read history entries. Returns last ``limit`` entries (0 = all)."""
        if not self.history_path or not self.history_path.exists():
            return []
        entries = []
        for line in self.history_path.read_text().strip().splitlines():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if limit > 0:
            return entries[-limit:]
        return entries

    def clear(self) -> None:
        """Remove the state file (history is preserved)."""
        if self.state_path.exists():
            self.state_path.unlink()

    def clear_history(self) -> None:
        """Remove the history file."""
        if self.history_path and self.history_path.exists():
            self.history_path.unlink()
