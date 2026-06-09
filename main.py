# -*- coding: utf-8 -*-
"""复读用户消息，用于调试被动回复与主动推送能否被其他插件处理。"""

from __future__ import annotations

import copy
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star

_SEND_PASSIVE = "passive"
_SEND_PROACTIVE = "proactive"


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


def _should_skip(event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
    if str(event.get_sender_id()) == str(event.get_self_id()):
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


class MsgDebuggerStar(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.cfg = config

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_passive_echo(self, event: AstrMessageEvent):
        """被动回复：yield 结果，经 ResultDecorate -> Respond 出站。"""
        if _send_mode(self.cfg) != _SEND_PASSIVE or _should_skip(event, self.cfg):
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
        if _send_mode(self.cfg) != _SEND_PROACTIVE or _should_skip(event, self.cfg):
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
