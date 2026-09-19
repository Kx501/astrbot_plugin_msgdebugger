"""Bounded, detached conversation records."""

from __future__ import annotations

import copy
import json
import sqlite3
import threading
import time
import uuid
from collections import OrderedDict

from astrbot.api import logger

from .trace_persist import clear_file, load_traces, upsert_trace


class TraceStore:
    def __init__(self, data_dir, config) -> None:
        self.path = data_dir / "traces.sqlite3"
        self.persist = bool(config.get("persist_traces", True))
        key = "max_persist_entries" if self.persist else "max_trace_entries"
        self.limit = max(10, min(int(config.get(key, 200)), 1000))
        self.lock = threading.RLock()
        self.traces = OrderedDict()
        self.error = None
        if self.persist:
            try:
                for trace in load_traces(self.path, limit=self.limit):
                    trace["snapshot_bytes"] = len(
                        json.dumps(trace, ensure_ascii=False).encode("utf-8")
                    )
                    self.traces[trace["id"]] = trace
            except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
                self.error = f"Persistence unavailable: {type(exc).__name__}"
                self.persist = False
                logger.exception("MsgDebugger persistence unavailable; using memory")

    def record(self, event, kind, fields) -> None:
        """Append a bounded snapshot without retaining live event references.

        Args:
            event: Conversation event used for identity and display metadata.
            kind: Stage category.
            fields: Detached payload.
        """
        with self.lock:
            trace_id = event.get_extra("_md_trace_id")
            if not trace_id:
                trace_id = uuid.uuid4().hex
                event.set_extra("_md_trace_id", trace_id)
            if trace_id not in self.traces:
                self.traces[trace_id] = {
                    "id": trace_id,
                    "schema_version": 2,
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "umo": str(event.unified_msg_origin),
                    "sender_id": str(event.get_sender_id()),
                    "sender_name": str(event.get_sender_name() or "")
                    if hasattr(event, "get_sender_name")
                    else "",
                    "platform_id": str(event.get_platform_id())
                    if hasattr(event, "get_platform_id")
                    else "",
                    "chat_type": ("private" if event.is_private_chat() else "group")
                    if hasattr(event, "is_private_chat")
                    else "unknown",
                    "group_id": str(event.get_group_id() or "")
                    if hasattr(event, "get_group_id")
                    else "",
                    "group_name": str(
                        getattr(
                            getattr(getattr(event, "message_obj", None), "group", None),
                            "group_name",
                            "",
                        )
                        or ""
                    ),
                    "summary": str(event.message_str or "")[:120],
                    "stages": [],
                    "snapshot_bytes": 0,
                }
            trace = self.traces[trace_id]
            if trace.get("closed_by_limit"):
                return
            size = len(json.dumps(fields, ensure_ascii=False).encode("utf-8"))
            if size > 256 * 1024:
                fields = [
                    {
                        "key": "detail",
                        "format": "json",
                        "json": {
                            "truncated": True,
                            "reason": "Stage exceeded 256 KiB",
                            "original_bytes": size,
                        },
                    }
                ]
                size = 256
                trace["truncated"] = True
            if (
                len(trace["stages"]) >= 300
                or trace["snapshot_bytes"] + size > 2 * 1024 * 1024
            ):
                trace["truncated"] = True
                trace["closed_by_limit"] = True
            else:
                trace["stages"].append(
                    {
                        "key": kind,
                        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "fields": copy.deepcopy(fields),
                    }
                )
                trace["snapshot_bytes"] += size
            if self.persist:
                try:
                    upsert_trace(self.path, trace, limit=self.limit)
                except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as exc:
                    self.error = f"Persistence failed: {type(exc).__name__}"
                    self.persist = False
                    logger.exception("MsgDebugger persistence failed; using memory")
            total = sum(t.get("snapshot_bytes", 0) for t in self.traces.values())
            while len(self.traces) > self.limit or (
                total > 64 * 1024 * 1024 and len(self.traces) > 1
            ):
                _, removed = self.traces.popitem(last=False)
                total -= removed.get("snapshot_bytes", 0)

    def summaries(self) -> list[dict]:
        """Return navigation metadata without prompt bodies.

        Returns:
            Up to 200 recent trace summaries.
        """
        with self.lock:
            return [
                {
                    **{k: v for k, v in t.items() if k != "stages"},
                    "stage_count": len(t["stages"]),
                }
                for t in reversed(self.traces.values())
            ][:200]

    def detail(self, trace_id: str) -> dict | None:
        """Read a detached trace.

        Args:
            trace_id: Trace identifier.

        Returns:
            Trace snapshot or None when expired.
        """
        with self.lock:
            return copy.deepcopy(self.traces.get(trace_id))

    def clear(self) -> None:
        """Clear current records and the database, preserving the legacy archive."""
        with self.lock:
            clear_file(self.path)
            self.traces.clear()
