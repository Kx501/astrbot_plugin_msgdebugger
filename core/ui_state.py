# -*- coding: utf-8 -*-
"""Logs 页面 UI 状态持久化。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

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
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("MsgDebugger: read ui state failed: %s", exc)
        return {}
    return _pick_ui(data)


def save_ui_state(path: Path, raw: Any) -> bool:
    ui = _pick_ui(raw)
    if not ui:
        _log.warning("MsgDebugger: ui state payload empty or invalid")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps({"ui": ui}, ensure_ascii=False, indent=2)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
        tmp.replace(path)
        return True
    except OSError as exc:
        _log.error("MsgDebugger: write ui state failed: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
