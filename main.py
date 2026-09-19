"""AstrBot transparent debugger and independent echo probe."""

from __future__ import annotations

import copy

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools

from .core.observer import DebugObserver, snapshot, tool_info
from .core.page_api import register_trace_page_routes
from .core.runtime import RUNTIME
from .core.trace_store import TraceStore

PLUGIN_NAME = "astrbot_plugin_msgdebugger"


class MsgDebuggerStar(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.cfg = config
        data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.store = TraceStore(data_dir, config)
        self.observer = DebugObserver(context, self._record_stage)
        register_trace_page_routes(context, self.store, config, observer=self.observer)
        self._page_handlers = {
            id(entry[1])
            for entry in context.registered_web_apis
            if entry[0].startswith(f"/{PLUGIN_NAME}/page/")
        }

    def _record_stage(self, event, kind, fields) -> None:
        """Write an observer record when collection is enabled.

        Args:
            event: Owning conversation event.
            kind: Observation category.
            fields: Detached stage fields.
        """
        if self.cfg.get("trace_enabled", True):
            self.store.record(event, kind, fields)

    async def initialize(self) -> None:
        """Install observation adapters after registration."""
        if self.cfg.get("trace_enabled", True):
            self.observer.install()

    async def terminate(self) -> None:
        """Restore adapters and discard temporary echo overrides."""
        self.observer.uninstall()
        self.context.registered_web_apis[:] = [
            entry
            for entry in self.context.registered_web_apis
            if id(entry[1]) not in self._page_handlers
        ]
        RUNTIME.set_echo(None)

    @filter.command("md")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def md_command(self, event: AstrMessageEvent):
        """Control the echo probe from an administrator conversation.

        Args:
            event: Command message event.
        """
        parts = event.get_message_str().strip().lower().split()
        action = parts[-1] if len(parts) >= 3 and parts[-2] == "echo" else "status"
        if action in ("on", "off", "reset"):
            RUNTIME.set_echo({"on": True, "off": False, "reset": None}[action])
        yield event.plain_result(
            f"复读：{RUNTIME.echo_status(bool(self.cfg.get('echo_enabled', False)))}\n"
            "用法：/md echo on|off|status|reset；完整调试请打开插件 Pages → logs。"
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10000)
    async def inbound(self, event: AstrMessageEvent) -> None:
        """Record inbound messages without consuming them.

        Args:
            event: Incoming platform message.
        """
        if str(event.get_sender_id()) != str(event.get_self_id()):
            self.observer.emit(
                event,
                "inbound",
                {"text": event.message_str, "chain": snapshot(event.get_messages())},
            )

    @filter.on_llm_request(priority=-10000)
    async def request_snapshot(self, event, req) -> None:
        """Capture hook-level requests and optional extension reports.

        Args:
            event: Owning conversation event.
            req: Request visible at this hook boundary.
        """
        self.observer.emit(
            event,
            "request_snapshot",
            {
                "level": "plugin_hook",
                "request": self.observer.handler_snapshot(event, (req,)).get("request"),
            },
        )
        reports = event.get_extra("_msgdebugger_events", [])
        if isinstance(reports, list):
            for report in reports[:100]:
                if isinstance(report, dict):
                    self.observer.emit(
                        event,
                        "extension",
                        {"evidence": "plugin_reported", "report": report},
                    )
            event.set_extra("_msgdebugger_events", [])

    @filter.on_llm_response()
    async def response(self, event, resp) -> None:
        """Record the final agent response separately from per-attempt usage.

        Args:
            event: Owning conversation event.
            resp: Final response reported by AstrBot.
        """
        self.observer.emit(event, "llm_response", {"response": snapshot(resp)})

    @filter.on_using_llm_tool()
    async def tool_start(self, event, tool, tool_args) -> None:
        """Record selected tool ownership and arguments.

        Args:
            event: Owning conversation event.
            tool: Selected tool.
            tool_args: Execution arguments.
        """
        self.observer.emit(
            event,
            "tool_start",
            {"tool": tool_info(tool), "arguments": snapshot(tool_args)},
        )

    @filter.on_llm_tool_respond()
    async def tool_end(self, event, tool, tool_args, tool_result) -> None:
        """Record the observed tool result.

        Args:
            event: Owning conversation event.
            tool: Executed tool.
            tool_args: Execution arguments.
            tool_result: Result reported by AstrBot.
        """
        self.observer.emit(
            event,
            "tool_end",
            {
                "tool": tool_info(tool),
                "arguments": snapshot(tool_args),
                "result": snapshot(tool_result),
            },
        )

    @filter.on_decorating_result(priority=-10000)
    async def decorating(self, event) -> None:
        """Capture output at the decoration hook.

        Args:
            event: Owning conversation event.
        """
        self.observer.emit(
            event, "decorating", {"result": snapshot(event.get_result())}
        )

    @filter.after_message_sent()
    async def sent(self, event) -> None:
        """Record the framework's sent notification.

        Args:
            event: Owning conversation event.
        """
        self.observer.emit(
            event,
            "sent",
            {
                "result": snapshot(event.get_result()),
                "evidence": "after_message_sent_hook",
            },
        )

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def echo(self, event: AstrMessageEvent):
        """Echo eligible messages using the configured send path.

        Args:
            event: Incoming platform message.
        """
        if not RUNTIME.echo_enabled(bool(self.cfg.get("echo_enabled", False))):
            return
        if str(event.get_sender_id()) == str(event.get_self_id()):
            return
        prefixes = self.context.get_config(umo=event.unified_msg_origin).get(
            "wake_prefix"
        ) or ["/"]
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(
            event.message_str.strip().startswith(p)
            for p in prefixes
            if isinstance(p, str) and p
        ):
            return
        users = {str(v).strip() for v in self.cfg.get("user_whitelist", [])}
        groups = {str(v).strip() for v in self.cfg.get("group_whitelist", [])}
        if users and str(event.get_sender_id()) not in users:
            return
        if (
            groups
            and not event.is_private_chat()
            and str(event.get_group_id()) not in groups
        ):
            return
        if self.cfg.get("echo_content", "plain") == "chain":
            chain = copy.deepcopy(event.get_messages())
        else:
            from astrbot.api.message_components import Plain

            chain = [Plain(event.message_str)] if event.message_str else []
        if not chain:
            return
        mode = self.cfg.get("send_mode", "passive")
        self.observer.emit(
            event, "echo_start", {"mode": mode, "chain": snapshot(chain)}
        )
        if mode == "proactive":
            try:
                result = await self.context.send_message(
                    event.unified_msg_origin, MessageChain(chain)
                )
                self.observer.emit(
                    event, "echo_sent", {"mode": mode, "send_return": snapshot(result)}
                )
            except Exception as exc:  # noqa: BLE001 - Platform failures must not abort other handlers.
                self.observer.emit(event, "echo_error", {"error": type(exc).__name__})
                logger.exception("MsgDebugger echo send failed")
        else:
            yield event.chain_result(chain)
