# -*- coding: utf-8 -*-
"""AstrBot Plugin Pages API（懒加载，不依赖 astrbot.api.web）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .runtime import RUNTIME
from .ui_state import load_ui_state, save_ui_state

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
    data_dir: Path | None = None,
) -> bool:
    """注册 logs 页面 API；不可用时返回 False。"""
    register = getattr(context, "register_web_api", None)
    if not callable(register):
        return False

    ui_state_path = (data_dir / "logs_ui.json") if data_dir else None

    async def list_traces() -> dict:
        return {"status": "ok", "data": {"traces": store.list_traces()}}

    async def clear_traces() -> dict:
        store.clear()
        return {"status": "ok", "data": {"cleared": True}}

    async def runtime_status() -> dict:
        echo_cfg = bool(cfg.get("echo_enabled", True)) if cfg else True
        data = RUNTIME.snapshot(echo_cfg=echo_cfg)
        data["ui"] = load_ui_state(ui_state_path) if ui_state_path else {}
        return {"status": "ok", "data": data}

    async def save_runtime() -> dict:
        from astrbot.api import logger

        if not ui_state_path:
            return {"status": "error", "message": "UI state path unavailable"}
        try:
            from astrbot.api.web import request as plugin_request
        except ImportError:
            return {"status": "error", "message": "web request unavailable"}
        body = await _read_json_body(plugin_request)
        if not save_ui_state(ui_state_path, body):
            logger.warning("MsgDebugger: ui state save rejected, body=%s", type(body).__name__)
            return {"status": "error", "message": "invalid ui state payload"}
        logger.info("MsgDebugger: ui state saved -> %s", ui_state_path)
        return {"status": "ok", "data": {"saved": True}}

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
    register(
        f"{PAGE_PREFIX}/runtime",
        save_runtime,
        ["POST"],
        "Save MsgDebugger logs page UI state",
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
