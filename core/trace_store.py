# -*- coding: utf-8 -*-
"""内存环形缓冲：按 trace 分组记录管线阶段。"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

from .formatters import (
    format_chain,
    format_extra_parts,
    format_prompt,
    format_system_prompt,
    format_token_usage,
    pick_event_extras,
    summarize_text,
)

TRACE_EXTRA_KEY = "_md_trace_id"


class TraceStore:
    def __init__(self, max_traces: int = 200) -> None:
        self._max = max(10, int(max_traces))
        self._lock = threading.Lock()
        self._traces: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def set_max_traces(self, max_traces: int) -> None:
        self._max = max(10, int(max_traces))
        with self._lock:
            self._trim()

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()

    def ensure_trace_id(self, event: Any) -> str:
        get_extra = getattr(event, "get_extra", None)
        set_extra = getattr(event, "set_extra", None)
        if callable(get_extra):
            existing = get_extra(TRACE_EXTRA_KEY)
            if isinstance(existing, str) and existing:
                return existing
        trace_id = uuid.uuid4().hex[:12]
        if callable(set_extra):
            set_extra(TRACE_EXTRA_KEY, trace_id)
        return trace_id

    def begin_trace(self, trace_id: str, meta: dict[str, Any]) -> None:
        with self._lock:
            if trace_id in self._traces:
                return
            self._traces[trace_id] = {
                "id": trace_id,
                "started_at": meta.get("at") or _now_iso(),
                "umo": meta.get("umo", ""),
                "chat": meta.get("chat", ""),
                "sender_id": meta.get("sender_id", ""),
                "sender_name": meta.get("sender_name", ""),
                "group_id": meta.get("group_id", ""),
                "summary": meta.get("summary", ""),
                "stages": [],
            }
            self._trim()

    def add_stage(self, trace_id: str, stage: str, fields: list[dict[str, Any]]) -> None:
        if not trace_id or not fields:
            return
        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                return
            stages: list[dict[str, Any]] = trace["stages"]
            stages.append(
                {
                    "key": stage,
                    "at": _now_iso(),
                    "fields": fields,
                }
            )

    def list_traces(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._traces.values()))

    def _trim(self) -> None:
        while len(self._traces) > self._max:
            self._traces.popitem(last=False)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def build_inbound_fields(event: Any) -> list[dict[str, Any]]:
    message_str = getattr(event, "message_str", None) or ""
    chain = []
    get_messages = getattr(event, "get_messages", None)
    if callable(get_messages):
        try:
            chain = get_messages()
        except Exception:
            chain = []
    return [
        _field("message_str", "原始文本", "text", message_str),
        _field("chain", "消息链", "lines", format_chain(chain)),
    ]


def build_llm_request_fields(event: Any, req: Any) -> list[dict[str, Any]]:
    prompt = format_prompt(getattr(req, "prompt", None))
    system = format_system_prompt(getattr(req, "system_prompt", None))
    extras = format_extra_parts(getattr(req, "extra_user_content_parts", None))
    event_extras = pick_event_extras(event)

    fields: list[dict[str, Any]] = [
        _field("prompt", "Prompt", "prompt", prompt),
        _field("system", "System", "system", system),
    ]
    if extras:
        fields.append(_field("extra_parts", "Extra 块", "extras", extras))
    if event_extras:
        fields.append(_field("event_extras", "Event Extra", "json", event_extras))

    session_id = getattr(req, "session_id", None)
    if session_id:
        fields.append(_field("session_id", "Session", "text", str(session_id)))

    image_urls = getattr(req, "image_urls", None) or []
    audio_urls = getattr(req, "audio_urls", None) or []
    if image_urls:
        fields.append(_field("images", "图片", "lines", [str(u) for u in image_urls]))
    if audio_urls:
        fields.append(_field("audios", "音频", "lines", [str(u) for u in audio_urls]))

    return fields


def build_llm_response_fields(resp: Any) -> list[dict[str, Any]]:
    text = ""
    try:
        text = resp.completion_text or ""
    except Exception:
        text = getattr(resp, "_completion_text", "") or ""

    chain = []
    result = getattr(resp, "result_chain", None)
    if result is not None:
        chain = getattr(result, "chain", None) or []

    fields: list[dict[str, Any]] = [
        _field("completion", "回复文本", "text", text),
    ]
    chain_lines = format_chain(chain)
    if chain_lines:
        fields.append(_field("chain", "回复链", "lines", chain_lines))

    reasoning = getattr(resp, "reasoning_content", None)
    if reasoning:
        fields.append(_field("reasoning", "Reasoning", "text", str(reasoning)))

    usage = format_token_usage(getattr(resp, "usage", None))
    if usage:
        fields.append(_field("tokens", "Token", "text", usage))

    tools = getattr(resp, "tools_call_name", None) or []
    if tools:
        fields.append(_field("tools", "工具调用", "lines", [str(t) for t in tools]))

    return fields


def build_decorating_fields(event: Any) -> list[dict[str, Any]]:
    result = event.get_result() if hasattr(event, "get_result") else None
    chain = getattr(result, "chain", None) if result is not None else None
    lines = format_chain(chain if isinstance(chain, list) else [])
    plain = "\n".join(
        line[7:] if line.startswith("[Plain] ") else line for line in lines
    )
    return [
        _field("chain", "出站链", "lines", lines),
        _field("plain", "纯文本预览", "text", plain),
    ]


def build_sent_fields(event: Any, *, echo_mode: str | None = None) -> list[dict[str, Any]]:
    fields = [_field("status", "状态", "text", "已发送")]
    if echo_mode:
        fields.append(_field("echo_mode", "调试复读", "text", echo_mode))
    stopped = bool(getattr(event, "is_stopped", lambda: False)())
    fields.append(_field("stopped", "事件已终止", "text", "是" if stopped else "否"))
    return fields


def _field(
    key: str,
    label: str,
    fmt: str,
    value: Any,
) -> dict[str, Any]:
    item: dict[str, Any] = {"key": key, "label": label, "format": fmt}
    if fmt == "text":
        item["text"] = value or ""
        item["summary"] = summarize_text(item["text"])
    elif fmt == "lines":
        item["lines"] = value if isinstance(value, list) else []
        item["summary"] = summarize_text("\n".join(item["lines"]))
    elif fmt == "prompt":
        item["prompt"] = value if isinstance(value, dict) else format_prompt(str(value))
        item["summary"] = summarize_text(item["prompt"].get("text") or "")
    elif fmt == "system":
        item["system"] = value if isinstance(value, dict) else format_system_prompt(str(value))
        item["summary"] = summarize_text(item["system"].get("text") or "")
    elif fmt == "extras":
        item["extras"] = value if isinstance(value, list) else []
        item["summary"] = summarize_text(
            "\n".join(row.get("text", "") for row in item["extras"] if isinstance(row, dict))
        )
    elif fmt == "json":
        item["json"] = value if isinstance(value, dict) else {}
        item["summary"] = summarize_text(str(item["json"]))
    else:
        item["text"] = str(value)
        item["summary"] = summarize_text(item["text"])
    return item
