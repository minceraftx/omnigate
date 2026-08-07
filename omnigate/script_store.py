"""Script store: save/load/delete named command-sequence scripts (JSON).

Scripts live in omnigate/scripts/<name>.json. A script is a list of command
dicts, e.g. [{"cmd": "navigate", "url": "..."}, {"cmd": "extract", "field": "text"}].
Content is maintained by the model (recorded from successful improv runs);
this module only handles persistence.
"""
from __future__ import annotations

import json
from pathlib import Path


class ScriptStore:
    def __init__(self, scripts_dir: str | None = None):
        default = Path(__file__).parent / "scripts"
        self.dir = Path(scripts_dir) if scripts_dir else default
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, steps: list[dict]) -> Path:
        """Save a script. Sanitizes name to a safe filename."""
        safe = "".join(c for c in name if c.isalnum() or c in "-_").strip()
        if not safe:
            raise ValueError(f"Invalid script name: {name}")
        path = self.dir / f"{safe}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(steps, f, ensure_ascii=False, indent=2)
        return path

    def load(self, name: str) -> list[dict]:
        path = self.dir / f"{name}.json"
        if not path.exists():
            raise KeyError(f"Script not found: {name}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list_names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.json"))

    def delete(self, name: str) -> None:
        path = self.dir / f"{name}.json"
        if path.exists():
            path.unlink()
        else:
            raise KeyError(f"Script not found: {name}")
