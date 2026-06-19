# -*- coding: utf-8 -*-
"""将管线中的消息与请求格式化为便于阅读的字段。"""

from __future__ import annotations

import re
from typing import Any

_MSG_TAG_RE = re.compile(
    r'^<msg\s+([^>]*?)>([\s\S]*)</msg>\s*$',
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def format_chain(chain: Any) -> list[str]:
    if not isinstance(chain, list):
        return []
    lines: list[str] = []
    for comp in chain:
        lines.append(_format_component(comp))
    return [line for line in lines if line]


def _format_component(comp: Any) -> str:
    name = type(comp).__name__
    text = getattr(comp, "text", None)
    if isinstance(text, str) and text:
        preview = text if len(text) <= 500 else text[:497] + "..."
        return f"[{name}] {preview}"

    for attr, label in (
        ("qq", "qq"),
        ("url", "url"),
        ("file", "file"),
        ("path", "path"),
        ("id", "id"),
    ):
        val = getattr(comp, attr, None)
        if val is not None and str(val).strip():
            return f"[{name}] {label}={val}"

    return f"[{name}]"


def format_prompt(text: str | None) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {"kind": "empty", "text": ""}

    match = _MSG_TAG_RE.match(raw)
    if not match:
        return {"kind": "text", "text": raw}

    attrs_block, body = match.group(1), match.group(2)
    attrs = {k: v for k, v in _ATTR_RE.findall(attrs_block)}
    return {
        "kind": "msg_tag",
        "attrs": attrs,
        "body": body,
        "text": raw,
        "lines": [
            f'user="{attrs.get("user", "")}" id="{attrs.get("id", "")}"',
            body,
        ],
    }


def format_system_prompt(text: str | None) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {"kind": "empty", "text": ""}

    parts = re.split(r"(?=<[a-zA-Z_][\w-]*>)", raw)
    segments = [part.strip() for part in parts if part and part.strip()]
    if len(segments) <= 1:
        return {"kind": "text", "text": raw}
    return {"kind": "segments", "text": raw, "segments": segments}


def format_extra_parts(parts: Any) -> list[dict[str, str]]:
    if not isinstance(parts, list):
        return []
    rows: list[dict[str, str]] = []
    for idx, part in enumerate(parts, start=1):
        text = getattr(part, "text", None)
        if text is None and isinstance(part, dict):
            text = part.get("text")
        temp = bool(getattr(part, "_no_save", False))
        if isinstance(part, dict) and part.get("_no_save"):
            temp = True
        label = f"extra#{idx}"
        if temp:
            label += " (temp)"
        rows.append(
            {
                "label": label,
                "text": _plain_text(text),
            }
        )
    return rows


def pick_event_extras(event: Any) -> dict[str, Any]:
    if event is None:
        return {}
    get_extra = getattr(event, "get_extra", None)
    if not callable(get_extra):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "_ii_injected",
        "_mp_pending_batches",
        "_md_trace_id",
        "_llm_reasoning_content",
    ):
        val = get_extra(key)
        if val is not None:
            out[key] = val
    return out


def format_token_usage(usage: Any) -> str | None:
    if usage is None:
        return None
    try:
        total = getattr(usage, "total", None)
        inp = getattr(usage, "input", None)
        out = getattr(usage, "output", None)
        cached = getattr(usage, "input_cached", None)
        if total is not None:
            bits = [f"total={total}"]
            if inp is not None:
                bits.append(f"in={inp}")
            if out is not None:
                bits.append(f"out={out}")
            if cached:
                bits.append(f"cached={cached}")
            return ", ".join(bits)
    except Exception:
        pass
    return _plain_text(usage) or None


def summarize_text(text: str | None, limit: int = 120) -> str:
    raw = (text or "").replace("\n", "\\n").strip()
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."
