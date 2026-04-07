from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
INDEX_PATH = OUTPUT_DIR / "cache_index.json"
LEGACY_INDEX_PATH = PROJECT_ROOT / "cache_index.json"


def resolve_project_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _to_index_path(path: Path) -> str:
    abs_path = resolve_project_path(path)
    try:
        return str(abs_path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(abs_path)


def load_index() -> dict[str, Any]:
    path = INDEX_PATH if INDEX_PATH.exists() else LEGACY_INDEX_PATH
    if not path.exists():
        return {"items": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"items": {}}
        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}
        return data
    except json.JSONDecodeError:
        return {"items": {}}


def save_index(index_data: dict[str, Any]) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_cached_file(path: Path, content: str) -> None:
    abs_path = resolve_project_path(path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")


def get_cached_content(index_data: dict[str, Any], key: str) -> tuple[Path | None, str | None]:
    item = index_data.get("items", {}).get(key)
    if not isinstance(item, dict):
        return None, None
    raw_path = item.get("path")
    if not raw_path:
        return None, None
    p = resolve_project_path(Path(raw_path))
    if not p.exists():
        return None, None
    return p, p.read_text(encoding="utf-8")


def get_cached_path(index_data: dict[str, Any], key: str) -> Path | None:
    item = index_data.get("items", {}).get(key)
    if not isinstance(item, dict):
        return None
    raw_path = item.get("path")
    if not raw_path:
        return None
    p = resolve_project_path(Path(raw_path))
    if not p.exists():
        return None
    return p


def index_put(index_data: dict[str, Any], key: str, record_id: str, path: Path) -> None:
    index_data.setdefault("items", {})
    index_data["items"][key] = {
        "id": record_id,
        "path": _to_index_path(path),
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }
