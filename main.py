# -*- coding: utf-8 -*-
"""复读用户消息，用于调试被动回复与主动推送能否被其他插件处理。"""

from __future__ import annotations

import copy
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star


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


class MsgDebuggerStar(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.cfg = config

    def _send_mode(self) -> str:
        mode = str(self.cfg.get("send_mode") or "passive").strip().lower()
        return mode if mode in {"passive", "proactive"} else "passive"

    def _echo_content(self) -> str:
        content = str(self.cfg.get("echo_content") or "plain").strip().lower()
        return content if content in {"plain", "chain"} else "plain"

    async def _send_proactive(self, event: AstrMessageEvent, chain: list[Any]) -> None:
        await self.context.send_message(event.unified_msg_origin, MessageChain(chain))

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent) -> None:
        """收到用户消息后按配置复读，用于调试主被动出站路径。"""
        if _should_skip(event, self.cfg):
            return

        mode = self._send_mode()
        content_mode = self._echo_content()

        if mode == "proactive":
            chain = (
                [Comp.Plain(event.message_str or "")]
                if content_mode == "plain"
                else copy.deepcopy(event.get_messages())
            )
            if not chain:
                return
            logger.debug(
                "MsgDebugger: proactive echo umo=%s content=%s",
                event.unified_msg_origin,
                content_mode,
            )
            await self._send_proactive(event, chain)
            return

        logger.debug(
            "MsgDebugger: passive echo umo=%s content=%s",
            event.unified_msg_origin,
            content_mode,
        )
        if content_mode == "chain":
            chain = copy.deepcopy(event.get_messages())
            if not chain:
                return
            yield event.chain_result(chain)
            return

        text = event.message_str or ""
        if not text:
            return
        yield event.plain_result(text)
