"""Bounded snapshots and reversible AstrBot observation adapters."""

# Observation boundaries must isolate arbitrary provider and plugin errors.
# ruff: noqa: BLE001

from __future__ import annotations

import dataclasses
import functools
import inspect
import json
import time
import uuid
from pathlib import Path
from typing import Any

from astrbot.api import logger


def snapshot(value: Any, depth: int = 0) -> Any:
    """Copy supported values without serializing arbitrary runtime objects.

    Args:
        value: Value to detach from live application state.
        depth: Current recursion depth.

    Returns:
        JSON-compatible data with explicit size-limit markers.
    """
    if depth > 16:
        return "[truncated: nesting limit]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if value.startswith("data:") and ";base64," in value[:100]:
            return "[omitted: inline media]"
        return (
            value if len(value) <= 64000 else value[:64000] + "[truncated: text limit]"
        )
    if isinstance(value, dict):
        result = {}
        for key, item in list(value.items())[:500]:
            name = str(key)
            result[name] = (
                "[redacted]"
                if name.lower()
                in {
                    "api_key",
                    "apikey",
                    "authorization",
                    "password",
                    "access_token",
                    "secret",
                }
                else snapshot(item, depth + 1)
            )
        if len(value) > 500:
            result["_truncated"] = "mapping limit"
        return result
    if isinstance(value, (list, tuple)):
        result = [snapshot(item, depth + 1) for item in value[:500]]
        if len(value) > 500:
            result.append("[truncated: list limit]")
        return result
    if hasattr(value, "model_dump"):
        try:
            return snapshot(value.model_dump(mode="json"), depth + 1)
        except Exception:
            return f"[unavailable: {type(value).__name__} serialization failed]"
    if hasattr(value, "completion_text") and hasattr(value, "tools_call_name"):
        return snapshot(
            {
                "_completion_text": value.completion_text,
                **{
                    name: getattr(value, name, None)
                    for name in (
                        "role",
                        "usage",
                        "result_chain",
                        "tools_call_name",
                        "tools_call_args",
                        "tools_call_ids",
                        "reasoning_content",
                        "is_chunk",
                    )
                },
            },
            depth + 1,
        )
    if dataclasses.is_dataclass(value):
        return snapshot(
            {f.name: getattr(value, f.name) for f in dataclasses.fields(value)},
            depth + 1,
        )
    return f"[unavailable: {type(value).__name__}]"


def tool_info(tool: Any) -> dict:
    """Describe a tool using its registered owner and schema.

    Args:
        tool: AstrBot function tool, optionally permission-wrapped.

    Returns:
        Tool schema and evidence for ownership.
    """
    from astrbot.core.star.star import star_map

    original = getattr(tool, "_wrapped", tool)
    module = getattr(original, "handler_module_path", None) or getattr(
        getattr(original, "handler", None), "__module__", ""
    )
    owner = star_map.get(module)
    ownership = "registered_plugin" if owner else "module_only"
    if not module:
        try:
            from astrbot.core.provider.register import llm_tools

            registered = llm_tools.get_tool(tool.name)
            matched_module = getattr(registered, "handler_module_path", None)
            matched_owner = star_map.get(matched_module)
            if matched_owner:
                owner = matched_owner
                ownership = "registered_name_match"
        except (ImportError, AttributeError):
            pass
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": snapshot(tool.parameters),
        "active": getattr(tool, "active", True),
        "source": owner.name if owner else (module or type(original).__module__),
        "ownership": ownership,
    }


class DebugObserver:
    """Observe handler boundaries and built-in runner attempts without dependencies."""

    def __init__(self, context, record) -> None:
        self.context = context
        self.record = record
        self.patches = []
        self.active = False
        self.coverage = {"handlers": False, "runner": False, "wire_payload": False}

    def emit(self, event, kind: str, data: dict) -> None:
        """Isolate collection failures from the conversation being observed.

        Args:
            event: Owning message event.
            kind: Observation category.
            data: Detached observation payload.
        """
        if not self.active or not hasattr(event, "unified_msg_origin"):
            return
        try:
            self.record(
                event,
                kind,
                [
                    {
                        "key": "detail",
                        "label": kind,
                        "format": "json",
                        "json": snapshot(data),
                    }
                ],
            )
        except Exception:
            logger.debug("MsgDebugger observation failed", exc_info=True)

    def handler_snapshot(self, event, args) -> dict:
        """Capture only inspectable message and request state.

        Args:
            event: Current event.
            args: Handler positional arguments containing an optional request.

        Returns:
            Detached state or a collection-error marker.
        """
        try:
            result = {
                "message": getattr(event, "message_str", ""),
                "stopped": event.is_stopped(),
                "result": snapshot(event.get_result()),
                "chain": snapshot(event.get_messages())
                if hasattr(event, "get_messages")
                else None,
            }
            for arg in args:
                if hasattr(arg, "system_prompt") and hasattr(arg, "contexts"):
                    result["request"] = {
                        key: snapshot(getattr(arg, key, None))
                        for key in (
                            "system_prompt",
                            "prompt",
                            "contexts",
                            "extra_user_content_parts",
                            "image_urls",
                            "audio_urls",
                            "model",
                        )
                    }
                    tools = getattr(arg, "func_tool", None)
                    result["request"]["tools"] = [
                        tool_info(t) for t in getattr(tools, "tools", [])
                    ]
                elif hasattr(arg, "completion_text"):
                    result["response"] = snapshot(arg)
                elif isinstance(arg, dict):
                    result.setdefault("arguments", []).append(snapshot(arg))
                elif hasattr(arg, "messages") and hasattr(arg, "context"):
                    result["agent_messages"] = snapshot(arg.messages)
            return result
        except Exception as exc:
            return {"unavailable": type(exc).__name__}

    def wrap_handler(self, metadata) -> None:
        """Wrap a handler once, preserving coroutine or generator semantics.

        Args:
            metadata: Mutable AstrBot handler registration.
        """
        if metadata.event_type.name not in {
            "AdapterMessageEvent",
            "OnWaitingLLMRequestEvent",
            "OnLLMRequestEvent",
            "OnLLMResponseEvent",
            "OnAgentBeginEvent",
            "OnAgentDoneEvent",
            "OnDecoratingResultEvent",
            "OnUsingLLMToolEvent",
            "OnLLMToolRespondEvent",
            "OnAfterMessageSentEvent",
        }:
            return
        original = metadata.handler
        if getattr(original, "_msgdebugger_observer", None) is self:
            return
        if "msgdebugger" in metadata.handler_module_path:
            return
        from astrbot.core.star.star import star_map

        owner = star_map.get(metadata.handler_module_path)
        source = owner.name if owner else metadata.handler_module_path
        base = {
            "source": source,
            "handler": metadata.handler_name,
            "hook": metadata.event_type.name,
            "evidence": "handler_boundary",
        }

        @functools.wraps(original)
        async def coroutine(event, *args, **kwargs):
            if not self.active:
                return await original(event, *args, **kwargs)
            before = self.handler_snapshot(event, args)
            started = time.perf_counter()
            error = None
            returned = None
            try:
                returned = await original(event, *args, **kwargs)
                return returned
            except BaseException as exc:
                error = type(exc).__name__
                raise
            finally:
                after = self.handler_snapshot(event, args)
                self.emit(
                    event,
                    "plugin_change",
                    {
                        **base,
                        "before": before if before != after else None,
                        "after": after if before != after else None,
                        "changed": before != after,
                        "yielded": snapshot(returned),
                        "error": error,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )

        @functools.wraps(original)
        async def generator(event, *args, **kwargs):
            iterator = original(event, *args, **kwargs)
            try:
                while True:
                    before = self.handler_snapshot(event, args) if self.active else {}
                    started = time.perf_counter()
                    try:
                        item = await iterator.__anext__()
                    except StopAsyncIteration:
                        after = (
                            self.handler_snapshot(event, args) if self.active else {}
                        )
                        if before != after:
                            self.emit(
                                event,
                                "plugin_change",
                                {
                                    **base,
                                    "before": before,
                                    "after": after,
                                    "changed": True,
                                },
                            )
                        break
                    except BaseException as exc:
                        self.emit(
                            event,
                            "plugin_change",
                            {**base, "error": type(exc).__name__},
                        )
                        raise
                    after = self.handler_snapshot(event, args) if self.active else {}
                    self.emit(
                        event,
                        "plugin_change",
                        {
                            **base,
                            "before": before if before != after else None,
                            "after": after if before != after else None,
                            "changed": before != after,
                            "yielded": snapshot(item),
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        },
                    )
                    # Snapshot each resume separately; downstream work is not this plugin's mutation.
                    yield item
            finally:
                await iterator.aclose()

        wrapper = generator if inspect.isasyncgenfunction(original) else coroutine
        if not (
            inspect.isasyncgenfunction(original)
            or inspect.iscoroutinefunction(original)
        ):
            return
        wrapper._msgdebugger_observer = self
        metadata.handler = wrapper
        self.patches.append((metadata, "handler", original, wrapper))

    def install(self) -> None:
        """Install independent adapters; unavailable adapters remain explicitly disabled."""
        if self.patches:
            return
        self.active = True
        try:
            from astrbot.core.star.star_handler import star_handlers_registry

            original = star_handlers_registry.get_handlers_by_event_type

            @functools.wraps(original)
            def handlers(*args, **kwargs):
                result = original(*args, **kwargs)
                if self.active:
                    for metadata in result:
                        try:
                            self.wrap_handler(metadata)
                        except Exception:
                            logger.debug(
                                "MsgDebugger handler adapter unavailable", exc_info=True
                            )
                return result

            star_handlers_registry.get_handlers_by_event_type = handlers
            self.patches.append(
                (
                    star_handlers_registry,
                    "get_handlers_by_event_type",
                    original,
                    handlers,
                )
            )
            self.coverage["handlers"] = True
        except Exception:
            logger.warning("MsgDebugger handler adapter unavailable", exc_info=True)
        try:
            from astrbot.core.agent.runners.tool_loop_agent_runner import (
                ToolLoopAgentRunner,
            )

            runner_original = ToolLoopAgentRunner._iter_llm_responses

            @functools.wraps(runner_original)
            async def responses(runner, *args, **kwargs):
                event = getattr(
                    getattr(getattr(runner, "run_context", None), "context", None),
                    "event",
                    None,
                )
                attempt = uuid.uuid4().hex
                started = time.perf_counter()
                try:
                    tools = runner._func_tool_for_provider()
                    self.emit(
                        event,
                        "model_request",
                        {
                            "attempt_id": attempt,
                            "level": "runner_before_provider_conversion",
                            "provider": runner.provider.provider_config.get("id"),
                            "model": runner.req.model
                            if kwargs.get("include_model", True)
                            else None,
                            "messages": snapshot(runner.run_context.messages),
                            "tools": [
                                tool_info(t) for t in getattr(tools, "tools", [])
                            ],
                            "extra_user_content_parts": snapshot(
                                runner.req.extra_user_content_parts
                            ),
                            "modalities": snapshot(
                                runner.provider.provider_config.get("modalities")
                            ),
                        },
                    )
                except Exception:
                    logger.debug(
                        "MsgDebugger runner snapshot unavailable", exc_info=True
                    )
                iterator = runner_original(runner, *args, **kwargs)
                completed = False
                try:
                    async for response in iterator:
                        if not getattr(response, "is_chunk", False):
                            completed = True
                            self.emit(
                                event,
                                "model_response",
                                {
                                    "attempt_id": attempt,
                                    "duration_ms": round(
                                        (time.perf_counter() - started) * 1000, 2
                                    ),
                                    "response": snapshot(response),
                                },
                            )
                        yield response
                except BaseException as exc:
                    completed = True
                    self.emit(
                        event,
                        "model_error",
                        {
                            "attempt_id": attempt,
                            "error": type(exc).__name__,
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        },
                    )
                    raise
                finally:
                    await iterator.aclose()
                    if not completed:
                        self.emit(
                            event,
                            "model_error",
                            {
                                "attempt_id": attempt,
                                "error": "No final response observed",
                                "duration_ms": round(
                                    (time.perf_counter() - started) * 1000, 2
                                ),
                            },
                        )

            ToolLoopAgentRunner._iter_llm_responses = responses
            self.patches.append(
                (ToolLoopAgentRunner, "_iter_llm_responses", runner_original, responses)
            )
            self.coverage["runner"] = True
        except Exception:
            logger.warning("MsgDebugger runner adapter unavailable", exc_info=True)

    def uninstall(self) -> None:
        """Restore only adapters still owned by this observer."""
        self.active = False
        for obj, name, original, wrapper in reversed(self.patches):
            if getattr(obj, name, None) is wrapper:
                setattr(obj, name, original)
        self.patches.clear()

    def inventory(self) -> dict:
        """Read current resource inventories without executing tools or skills.

        Returns:
            Tool and skill catalogs with independent availability errors.
        """
        result = {"tools": [], "skills": [], "errors": [], "coverage": self.coverage}
        try:
            result["tools"] = [
                tool_info(t) for t in self.context.provider_manager.llm_tools.func_list
            ]
        except Exception as exc:
            result["errors"].append(f"Tools unavailable: {type(exc).__name__}")
        try:
            import yaml
            from astrbot.core.utils.astrbot_path import (
                get_astrbot_builtin_plugin_path,
                get_astrbot_data_path,
                get_astrbot_plugin_path,
                get_astrbot_skills_path,
            )

            # SkillManager.list_skills may rewrite configuration or rename files.
            # Inspect the existing directories without invoking that mutating API.
            config_path = Path(get_astrbot_data_path()) / "skills.json"
            config = (
                json.loads(config_path.read_text(encoding="utf-8"))
                if config_path.is_file()
                else {}
            )
            roots = [(Path(get_astrbot_skills_path()), "local", False)]
            plugins_root = Path(get_astrbot_plugin_path())
            if plugins_root.is_dir():
                roots.extend(
                    (p / "skills", p.name, True)
                    for p in sorted(plugins_root.iterdir())
                    if p.is_dir()
                )
            for plugin in self.context.get_all_stars():
                if plugin.reserved and plugin.root_dir_name:
                    roots.append(
                        (
                            Path(get_astrbot_builtin_plugin_path())
                            / plugin.root_dir_name
                            / "skills",
                            plugin.root_dir_name,
                            True,
                        )
                    )
            for root, source, plugin_root in roots:
                if not root.is_dir():
                    continue
                folders = ([root] if plugin_root else []) + [
                    p for p in sorted(root.iterdir()) if p.is_dir()
                ]
                for folder in folders:
                    path = folder / "SKILL.md"
                    if not path.is_file():
                        path = folder / "skill.md"
                    if not path.is_file():
                        continue
                    name = source if folder == root else folder.name
                    item = {
                        "name": name,
                        "path": str(path),
                        "source_label": source,
                        "plugin_name": source if plugin_root else "",
                        "active": config.get("skills", {})
                        .get(name, {})
                        .get("active", True),
                        "description": "",
                        "content": None,
                    }
                    try:
                        with path.open(encoding="utf-8") as stream:
                            content = stream.read(64001)
                        item["content"] = snapshot(content)
                        if content.startswith("---"):
                            parts = content.split("---", 2)
                            if len(parts) == 3:
                                frontmatter = yaml.safe_load(parts[1])
                                if isinstance(frontmatter, dict):
                                    item["description"] = str(
                                        frontmatter.get("description", "")
                                    )
                    except (OSError, UnicodeError, yaml.YAMLError):
                        item["content_error"] = (
                            "Local skill content or metadata unavailable"
                        )
                    result["skills"].append(item)
        except Exception as exc:
            result["errors"].append(f"Skills unavailable: {type(exc).__name__}")
        return result
