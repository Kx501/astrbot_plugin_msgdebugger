"""Debugger endpoints using the authenticated AstrBot Pages bridge."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .runtime import RUNTIME

if TYPE_CHECKING:
    from astrbot.api import AstrBotConfig
    from astrbot.api.star import Context

    from .trace_store import TraceStore

PLUGIN_NAME = "astrbot_plugin_msgdebugger"
PAGE_PREFIX = f"/{PLUGIN_NAME}/page"


def register_trace_page_routes(
    context: Context,
    store: TraceStore,
    cfg: AstrBotConfig | None = None,
    *,
    observer: Any = None,
) -> bool:
    """Register debugger routes behind the AstrBot Pages bridge.

    Args:
        context: AstrBot plugin context.
        store: Bounded trace storage.
        cfg: Plugin configuration.
        observer: Runtime observation adapters.

    Returns:
        Whether the route registration API is available.
    """
    register = getattr(context, "register_web_api", None)
    if not callable(register):
        return False

    async def list_traces() -> dict:
        return {"status": "ok", "data": {"traces": store.summaries()}}

    async def trace_detail() -> dict:
        from astrbot.api.web import request

        body = await _read_json_body(request)
        trace = store.detail(str(body.get("id", "")))
        if trace is None:
            return {"status": "error", "message": "记录已清理或不存在"}
        return {"status": "ok", "data": {"trace": trace}}

    async def inventory() -> dict:
        import asyncio

        data = await asyncio.to_thread(observer.inventory) if observer else {}
        return {"status": "ok", "data": data}

    async def echo_control() -> dict:
        from astrbot.api.web import request

        body = await _read_json_body(request)
        action = body.get("action")
        if action not in ("on", "off", "reset"):
            return {"status": "error", "message": "无效的复读操作"}
        RUNTIME.set_echo({"on": True, "off": False, "reset": None}[action])
        return await runtime_status()

    async def compare_requests() -> dict:
        import difflib

        from astrbot.api.web import request

        body = await _read_json_body(request)
        values = []
        for side in ("left", "right"):
            selection = body.get(side, {})
            if not isinstance(selection, dict):
                return {"status": "error", "message": "无效的对比选择"}
            trace = store.detail(str(selection.get("trace_id", "")))
            selected = None
            for stage in (trace or {}).get("stages", []):
                if stage["key"] != "model_request":
                    continue
                data = stage["fields"][0].get("json", {})
                if data.get("attempt_id") == selection.get("attempt_id"):
                    selected = data
                    break
            if selected is None:
                return {"status": "error", "message": "请选择两次已采集的模型请求"}
            if body.get("scope") == "base":
                selected = {
                    "messages": [
                        m
                        for m in selected.get("messages", [])
                        if isinstance(m, dict)
                        and m.get("role") in ("system", "developer")
                    ],
                    "tools": selected.get("tools", []),
                    "extra_user_content_parts": selected.get(
                        "extra_user_content_parts"
                    ),
                }
            else:
                selected = {k: v for k, v in selected.items() if k != "attempt_id"}
            # Expand embedded newlines for readable prompt diffs.
            values.append(
                json.dumps(selected, ensure_ascii=False, indent=2, sort_keys=True)
                .replace("\\n", "\n")
                .splitlines()
            )
        lines = list(
            difflib.unified_diff(
                *values, fromfile="上次请求", tofile="本次请求", lineterm=""
            )
        )
        return {
            "status": "ok",
            "data": {"lines": lines[:5000], "truncated": len(lines) > 5000},
        }

    async def clear_traces() -> dict:
        store.clear()
        return {"status": "ok", "data": {"cleared": True}}

    async def runtime_status() -> dict:
        echo_cfg = bool(cfg.get("echo_enabled", False)) if cfg else False
        data = RUNTIME.snapshot(echo_cfg=echo_cfg)
        data["storage_error"] = store.error
        data["coverage"] = observer.coverage if observer else {}
        data["send_mode"] = cfg.get("send_mode", "passive") if cfg else "passive"
        data["echo_content"] = cfg.get("echo_content", "plain") if cfg else "plain"
        data["trace_enabled"] = bool(cfg.get("trace_enabled", True)) if cfg else True
        return {"status": "ok", "data": data}

    register(f"{PAGE_PREFIX}/detail", trace_detail, ["POST"], "Read one debug trace")
    register(f"{PAGE_PREFIX}/inventory", inventory, ["GET"], "Read tools and skills")
    register(f"{PAGE_PREFIX}/echo", echo_control, ["POST"], "Control echo probe")
    register(
        f"{PAGE_PREFIX}/compare",
        compare_requests,
        ["POST"],
        "Compare recorded requests",
    )
    register(
        f"{PAGE_PREFIX}/traces",
        list_traces,
        ["GET"],
        "MsgDebugger pipeline traces",
    )
    register(
        f"{PAGE_PREFIX}/traces/clear",
        clear_traces,
        ["POST"],
        "Clear MsgDebugger pipeline traces",
    )
    register(
        f"{PAGE_PREFIX}/runtime",
        runtime_status,
        ["GET"],
        "MsgDebugger runtime flags",
    )
    return True


async def _read_json_body(plugin_request: Any) -> dict[str, Any]:
    body = await plugin_request.json(default=None)
    if isinstance(body, dict):
        return body
    raw = await plugin_request.body()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
