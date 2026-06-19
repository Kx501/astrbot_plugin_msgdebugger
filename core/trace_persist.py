# -*- coding: utf-8 -*-
"""Trace JSONL 持久化（抓包式合集）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_traces(path: Path, *, limit: int) -> list[dict[str, Any]]:
    if not path.is_file() or limit <= 0:
        return []
    traces: list[dict[str, Any]] = []
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
                if isinstance(row, dict) and row.get("id"):
                    traces.append(row)
    except OSError:
        return []
    if len(traces) > limit:
        traces = traces[-limit:]
    return traces


def append_trace(path: Path, trace: dict[str, Any], *, limit: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    _trim_file(path, limit)


def clear_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _trim_file(path: Path, limit: int) -> None:
    if limit <= 0 or not path.is_file():
        return
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except OSError:
        return
    if len(lines) <= limit:
        return
    keep = lines[-limit:]
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(ln if ln.endswith("\n") else ln + "\n" for ln in keep)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
