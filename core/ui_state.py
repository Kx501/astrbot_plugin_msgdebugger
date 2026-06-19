# -*- coding: utf-8 -*-
"""Logs 页面 UI 状态持久化。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_UI_KEYS = frozenset(
    {
        "preset",
        "stages",
        "fields",
        "optDiff",
        "optCollapse",
        "autoRefresh",
        "fastRefresh",
        "autoScroll",
        "filtersOpen",
        "umoFilter",
    }
)


def _pick_ui(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("ui")
    source = nested if isinstance(nested, dict) else raw
    return {key: source[key] for key in _UI_KEYS if key in source}


def load_ui_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return _pick_ui(data)


def save_ui_state(path: Path, raw: Any) -> None:
    ui = _pick_ui(raw)
    if not ui:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps({"ui": ui}, ensure_ascii=False, indent=2)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
