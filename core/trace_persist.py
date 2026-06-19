# -*- coding: utf-8 -*-
"""Trace JSONL 持久化（按 trace id upsert，保留最新快照）。"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _read_trace_map(path: Path) -> OrderedDict[str, dict[str, Any]]:
    by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    if not path.is_file():
        return by_id
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                trace_id = str(row.get("id") or "")
                if trace_id:
                    by_id[trace_id] = row
    except OSError as exc:
        _log.warning("MsgDebugger: read traces file failed: %s", exc)
    return by_id


def load_traces(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    items = list(_read_trace_map(path).values())
    if len(items) > limit:
        items = items[-limit:]
    return items


def upsert_trace(path: Path, trace: dict[str, Any], *, limit: int) -> None:
    trace_id = str(trace.get("id") or "")
    if not trace_id:
        return
    cap = max(10, int(limit))
    by_id = _read_trace_map(path)
    by_id[trace_id] = trace
    while len(by_id) > cap:
        by_id.popitem(last=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for item in by_id.values():
                f.write(
                    json.dumps(item, ensure_ascii=False, separators=(",", ":"), default=str)
                    + "\n"
                )
        tmp.replace(path)
    except OSError as exc:
        _log.error("MsgDebugger: write traces file failed: %s", exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def clear_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        _log.warning("MsgDebugger: clear traces file failed: %s", exc)
