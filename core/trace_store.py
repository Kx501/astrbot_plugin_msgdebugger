# -*- coding: utf-8 -*-
"""内存环形缓冲：按 trace 分组记录管线阶段。"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
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
from .trace_persist import append_trace, clear_file, load_traces

TRACE_EXTRA_KEY = "_md_trace_id"
LLM_BEFORE_EXTRA = "_md_llm_before"
_PERSIST_STAGE = "sent"


class TraceStore:
    def __init__(self, max_traces: int = 200) -> None:
        self._max = max(10, int(max_traces))
        self._lock = threading.Lock()
        self._traces: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._persist_enabled = False
        self._persist_path: Path | None = None
        self._persist_max = 500

    def configure_persist(
        self,
        *,
        enabled: bool,
        path: Path,
        max_entries: int,
    ) -> None:
        with self._lock:
            self._persist_enabled = enabled
            self._persist_path = path
            self._persist_max = max(10, int(max_entries))
            if enabled:
                self._load_persist_locked()

    def _load_persist_locked(self) -> None:
        if not self._persist_path:
            return
        for trace in load_traces(self._persist_path, limit=self._persist_max):
            trace_id = str(trace.get("id") or "")
            if trace_id:
                self._traces[trace_id] = trace
        self._trim()

    def set_max_traces(self, max_traces: int) -> None:
        if not self._persist_enabled:
            self._max = max(10, int(max_traces))
        with self._lock:
            if not self._persist_enabled:
                self._trim()

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()
            if self._persist_enabled and self._persist_path:
                clear_file(self._persist_path)

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
            if stage == _PERSIST_STAGE:
                self._persist_trace_locked(trace)

    def _persist_trace_locked(self, trace: dict[str, Any]) -> None:
        if not self._persist_enabled or not self._persist_path:
            return
        append_trace(
            self._persist_path,
            copy.deepcopy(trace),
            limit=self._persist_max,
        )

    def list_traces(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self._traces.values()))

    def _trim(self) -> None:
        cap = self._persist_max if self._persist_enabled else self._max
        while len(self._traces) > cap:
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


def build_llm_before_snapshot(req: Any) -> dict[str, Any]:
    extra_parts = getattr(req, "extra_user_content_parts", None) or []
    extra_texts: list[str] = []
    for part in extra_parts:
        text = getattr(part, "text", None)
        if isinstance(text, str):
            extra_texts.append(text)
    return {
        "prompt": (getattr(req, "prompt", None) or "").strip(),
        "system_prompt": (getattr(req, "system_prompt", None) or "").strip(),
        "extra_texts": extra_texts,
    }


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


def build_injection_fields(event: Any, req: Any) -> list[dict[str, Any]]:
    """对比注入前后，展示 InfoInjection 等插件写入的内容。"""
    get_extra = getattr(event, "get_extra", None)
    before: dict[str, Any] = {}
    if callable(get_extra):
        raw = get_extra(LLM_BEFORE_EXTRA)
        if isinstance(raw, dict):
            before = raw

    after_prompt = (getattr(req, "prompt", None) or "").strip()
    after_system = (getattr(req, "system_prompt", None) or "").strip()
    before_prompt = str(before.get("prompt") or "").strip()
    before_system = str(before.get("system_prompt") or "").strip()

    fields: list[dict[str, Any]] = []

    ii = None
    if callable(get_extra):
        ii = get_extra("_ii_injected")

    if isinstance(ii, dict) and ii.get("blocks"):
        rule_ids = ii.get("rule_ids") or []
        fields.append(
            _field(
                "injection_rules",
                "命中规则",
                "lines",
                [str(rid) for rid in rule_ids],
            )
        )
        block_lines: list[str] = []
        for block in ii.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            rid = block.get("rule_id", "?")
            pos = block.get("position", "?")
            eph = "temp" if block.get("ephemeral") else "persist"
            text = str(block.get("text") or "")
            if not text and block.get("text_len"):
                text = f"(仅记录长度 {block['text_len']})"
            block_lines.append(f"[{rid}] {pos} ({eph})\n{text}")
        if block_lines:
            fields.append(
                _field("injection_blocks", "注入内容", "lines", block_lines),
            )
        date = ii.get("date")
        if date:
            fields.append(_field("injection_date", "注入日", "text", str(date)))
    else:
        fields.append(
            _field(
                "injection_status",
                "注入状态",
                "text",
                "本轮无 InfoInjection 记录（可能未注入或插件未启用）",
            )
        )

    if before_prompt != after_prompt:
        fields.append(
            _field("prompt_before", "Prompt（注入前）", "prompt", format_prompt(before_prompt)),
        )

    if before_system != after_system:
        if after_system.startswith(before_system) and before_system:
            delta = after_system[len(before_system) :].strip()
            fields.append(_field("system_added", "System 追加", "system", format_system_prompt(delta)))
        elif before_system or after_system:
            fields.append(
                _field("system_diff", "System 变更", "system", format_system_prompt(after_system)),
            )

    before_extras = before.get("extra_texts") if isinstance(before.get("extra_texts"), list) else []
    after_extras = format_extra_parts(getattr(req, "extra_user_content_parts", None))
    after_texts = [row.get("text", "") for row in after_extras]
    if before_extras != after_texts:
        added = [t for t in after_texts if t not in before_extras]
        if added:
            fields.append(
                _field(
                    "extra_added",
                    "Extra 新增",
                    "lines",
                    [f"[+] {text}" for text in added],
                )
            )

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
