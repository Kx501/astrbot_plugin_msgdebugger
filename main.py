# -*- coding: utf-8 -*-
"""复读用户消息，并记录管线各阶段格式化日志。"""

from __future__ import annotations

import copy
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star

from .core.page_api import register_trace_page_routes
from .core.trace_store import (
    LLM_BEFORE_EXTRA,
    TraceStore,
    build_decorating_fields,
    build_inbound_fields,
    build_injection_fields,
    build_llm_before_snapshot,
    build_llm_request_fields,
    build_llm_response_fields,
    build_sent_fields,
)

PLUGIN_NAME = "astrbot_plugin_msgdebugger"
_SEND_PASSIVE = "passive"
_SEND_PROACTIVE = "proactive"
_TRACE_STORE = TraceStore()


def _as_str_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}


def _passes_whitelist(event: AstrMessageEvent, group_wl: set[str], user_wl: set[str]) -> bool:
    sender_id = str(event.get_sender_id())
    if user_wl and sender_id not in user_wl:
        return False
    if event.is_private_chat():
        return True
    if not group_wl:
        return True
    group_id = str(event.get_group_id() or "").strip()
    return group_id in group_wl


def _wake_prefixes(context: Context, event: AstrMessageEvent) -> list[str]:
    cfg = context.get_config(umo=event.unified_msg_origin)
    raw = cfg.get("wake_prefix") or ["/"]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(p) for p in raw if str(p)]
    return ["/"]


def _is_wake_command(event: AstrMessageEvent, context: Context) -> bool:
    msg_obj = event.message_obj
    raw = ((msg_obj.message_str if msg_obj else None) or "").strip()
    if not raw:
        return False
    for prefix in _wake_prefixes(context, event):
        if raw.startswith(prefix):
            return True
    return False


def _should_skip(event: AstrMessageEvent, cfg: AstrBotConfig, context: Context) -> bool:
    if str(event.get_sender_id()) == str(event.get_self_id()):
        return True
    if _is_wake_command(event, context):
        return True
    group_wl = _as_str_set(cfg.get("group_whitelist"))
    user_wl = _as_str_set(cfg.get("user_whitelist"))
    return not _passes_whitelist(event, group_wl, user_wl)


def _send_mode(cfg: AstrBotConfig) -> str:
    mode = str(cfg.get("send_mode") or _SEND_PASSIVE).strip().lower()
    return mode if mode in {_SEND_PASSIVE, _SEND_PROACTIVE} else _SEND_PASSIVE


def _echo_content(cfg: AstrBotConfig) -> str:
    content = str(cfg.get("echo_content") or "plain").strip().lower()
    return content if content in {"plain", "chain"} else "plain"


def _build_chain(event: AstrMessageEvent, content_mode: str) -> list[Any]:
    if content_mode == "plain":
        text = event.message_str or ""
        return [Comp.Plain(text)] if text else []
    return copy.deepcopy(event.get_messages())


def _sender_name(event: AstrMessageEvent) -> str:
    try:
        sender = event.message_obj.sender
        name = getattr(sender, "nickname", None) or getattr(sender, "user_id", None)
        if name:
            return str(name).strip()
    except Exception:
        pass
    return str(event.get_sender_id())


class MsgDebuggerStar(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.cfg = config
        self._sync_store_limit()
        self._register_page_api()

    def _register_page_api(self) -> None:
        if not hasattr(self.context, "register_web_api"):
            logger.warning("MsgDebugger: 当前 AstrBot 不支持 register_web_api，日志 Page 不可用")
            return
        try:
            if register_trace_page_routes(self.context, _TRACE_STORE):
                logger.info("MsgDebugger: 已注册 logs 页面 API")
        except Exception:
            logger.exception("MsgDebugger: 注册 logs 页面 API 失败")

    def _trace_enabled(self) -> bool:
        return bool(self.cfg.get("trace_enabled", True))

    def _sync_store_limit(self) -> None:
        try:
            limit = int(self.cfg.get("max_trace_entries") or 200)
        except (TypeError, ValueError):
            limit = 200
        _TRACE_STORE.set_max_traces(limit)

    def _trace_meta(self, event: AstrMessageEvent) -> dict[str, str]:
        chat = "私聊" if event.is_private_chat() else "群聊"
        message_str = (event.message_str or "").strip()
        return {
            "at": "",
            "umo": str(event.unified_msg_origin),
            "chat": chat,
            "sender_id": str(event.get_sender_id()),
            "sender_name": _sender_name(event),
            "group_id": str(event.get_group_id() or ""),
            "summary": message_str[:120],
        }

    def _record_stage(
        self,
        event: AstrMessageEvent,
        stage: str,
        fields: list[dict[str, Any]],
    ) -> None:
        if not self._trace_enabled() or not fields:
            return
        trace_id = _TRACE_STORE.ensure_trace_id(event)
        _TRACE_STORE.begin_trace(trace_id, self._trace_meta(event))
        _TRACE_STORE.add_stage(trace_id, stage, fields)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_trace_inbound(self, event: AstrMessageEvent) -> None:
        if not self._trace_enabled():
            return
        if str(event.get_sender_id()) == str(event.get_self_id()):
            return
        self._record_stage(event, "inbound", build_inbound_fields(event))

    @filter.on_llm_request(priority=100)
    async def on_trace_llm_request_before(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        if not self._trace_enabled():
            return
        event.set_extra(LLM_BEFORE_EXTRA, build_llm_before_snapshot(req))

    @filter.on_llm_request(priority=-100)
    async def on_trace_llm_request(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        if not self._trace_enabled():
            return
        self._record_stage(event, "llm_request", build_llm_request_fields(event, req))
        injection_fields = build_injection_fields(event, req)
        if injection_fields:
            self._record_stage(event, "injection", injection_fields)

    @filter.on_llm_response()
    async def on_trace_llm_response(self, event: AstrMessageEvent, resp: Any) -> None:
        if not self._trace_enabled():
            return
        self._record_stage(event, "llm_response", build_llm_response_fields(resp))

    @filter.on_decorating_result()
    async def on_trace_decorating(self, event: AstrMessageEvent) -> None:
        if not self._trace_enabled():
            return
        self._record_stage(event, "decorating", build_decorating_fields(event))

    @filter.after_message_sent()
    async def on_trace_sent(self, event: AstrMessageEvent) -> None:
        if not self._trace_enabled():
            return
        echo_mode = None
        if not _should_skip(event, self.cfg, self.context):
            echo_mode = _send_mode(self.cfg)
        self._record_stage(
            event,
            "sent",
            build_sent_fields(event, echo_mode=echo_mode),
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_passive_echo(self, event: AstrMessageEvent):
        """被动回复：yield 结果，经 ResultDecorate -> Respond 出站。"""
        if _send_mode(self.cfg) != _SEND_PASSIVE or _should_skip(
            event, self.cfg, self.context
        ):
            return

        chain = _build_chain(event, _echo_content(self.cfg))
        if not chain:
            return

        logger.debug(
            "MsgDebugger: passive echo umo=%s content=%s",
            event.unified_msg_origin,
            _echo_content(self.cfg),
        )
        yield event.chain_result(chain)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_proactive_echo(self, event: AstrMessageEvent) -> None:
        """主动推送：context.send_message，不经被动回复管线。"""
        if _send_mode(self.cfg) != _SEND_PROACTIVE or _should_skip(
            event, self.cfg, self.context
        ):
            return

        chain = _build_chain(event, _echo_content(self.cfg))
        if not chain:
            return

        logger.debug(
            "MsgDebugger: proactive echo umo=%s content=%s",
            event.unified_msg_origin,
            _echo_content(self.cfg),
        )
        await self.context.send_message(
            event.unified_msg_origin,
            MessageChain(chain),
        )
