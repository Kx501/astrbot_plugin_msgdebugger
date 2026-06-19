# -*- coding: utf-8 -*-
"""AstrBot Plugin Pages API（懒加载，不依赖 astrbot.api.web）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from .trace_store import TraceStore

PLUGIN_NAME = "astrbot_plugin_msgdebugger"
PAGE_PREFIX = f"/{PLUGIN_NAME}/page"


def register_trace_page_routes(context: Context, store: TraceStore) -> bool:
    """注册 logs 页面 API；不可用时返回 False。"""
    register = getattr(context, "register_web_api", None)
    if not callable(register):
        return False

    async def list_traces() -> dict:
        return {"status": "ok", "data": {"traces": store.list_traces()}}

    async def clear_traces() -> dict:
        store.clear()
        return {"status": "ok", "data": {"cleared": True}}

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
    return True
