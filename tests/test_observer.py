"""Focused observer contract tests using only the Python standard library."""

import asyncio
import importlib
import logging
import sqlite3
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for name in (
    "astrbot",
    "astrbot.api",
    "astrbot.core",
    "astrbot.core.star",
    "astrbot.core.star.star",
    "astrbot.core.star.star_handler",
    "astrbot.core.agent",
    "astrbot.core.agent.runners",
    "astrbot.core.agent.runners.tool_loop_agent_runner",
):
    sys.modules[name] = types.ModuleType(name)
sys.modules["astrbot.api"].logger = logging.getLogger("debugger-tests")
star_module = sys.modules["astrbot.core.star.star"]
star_module.star_map = {"plugin.alpha": SimpleNamespace(name="alpha")}
observer_module = importlib.import_module("core.observer")
TraceStore = importlib.import_module("core.trace_store").TraceStore


class Event:
    def __init__(self, name="one"):
        self.unified_msg_origin = name
        self.message_str = "hello"
        self.extra = {}
        self.result = None

    def get_extra(self, key, default=None):
        return self.extra.get(key, default)

    def set_extra(self, key, value):
        self.extra[key] = value

    def get_sender_id(self):
        return "user"

    def is_stopped(self):
        return False

    def get_result(self):
        return self.result


def metadata(handler):
    return SimpleNamespace(
        handler=handler,
        handler_module_path="plugin.alpha",
        handler_name="modify",
        event_type=SimpleNamespace(name="OnLLMRequestEvent"),
    )


def request():
    return SimpleNamespace(
        system_prompt="base",
        contexts=[],
        prompt="hello",
        func_tool=None,
        model="test",
        extra_user_content_parts=[],
    )


@dataclass
class Response:
    is_chunk: bool = False
    usage: dict | None = None


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.records = []
        self.observer = observer_module.DebugObserver(
            None,
            lambda event, kind, fields: self.records.append(
                (event.unified_msg_origin, kind, fields[0]["json"])
            ),
        )
        self.observer.active = True

    def tearDown(self):
        self.observer.uninstall()

    async def test_return_identity_and_detached_attribution(self):
        returned = object()

        async def handler(event, req):
            req.system_prompt += " changed"
            return returned

        meta = metadata(handler)
        req = request()
        self.observer.wrap_handler(meta)
        self.assertIs(await meta.handler(Event(), req), returned)
        data = self.records[0][2]
        self.assertEqual(data["source"], "alpha")
        self.assertEqual(data["before"]["request"]["system_prompt"], "base")
        req.system_prompt = "later"
        self.assertEqual(data["after"]["request"]["system_prompt"], "base changed")
        self.observer.uninstall()
        self.assertIs(meta.handler, handler)

    async def test_exceptions_and_cancellation_propagate(self):
        for exception in (ValueError("original"), asyncio.CancelledError()):

            async def handler(event, req, error=exception):
                raise error

            meta = metadata(handler)
            self.observer.wrap_handler(meta)
            with self.assertRaises(type(exception)) as caught:
                await meta.handler(Event(), request())
            self.assertIs(caught.exception, exception)

    async def test_generator_does_not_attribute_downstream_mutation(self):
        async def handler(event, req):
            req.prompt = "plugin"
            yield "first"
            yield "second"

        meta = metadata(handler)
        self.observer.wrap_handler(meta)
        req = request()
        iterator = meta.handler(Event(), req)
        self.assertEqual(await anext(iterator), "first")
        req.prompt = "downstream"
        self.assertEqual(await anext(iterator), "second")
        await iterator.aclose()
        self.assertTrue(self.records[0][2]["changed"])
        self.assertFalse(self.records[1][2]["changed"])

    async def test_observer_failure_does_not_change_handler_result(self):
        async def handler(event):
            return "ok"

        meta = metadata(handler)
        self.observer.record = lambda *args: (_ for _ in ()).throw(
            RuntimeError("storage")
        )
        self.observer.wrap_handler(meta)
        self.assertEqual(await meta.handler(Event()), "ok")

    async def test_lifecycle_callbacks_remain_unwrapped(self):
        async def handler():
            return "loaded"

        meta = metadata(handler)
        meta.event_type = SimpleNamespace(name="OnAstrBotLoadedEvent")
        self.observer.wrap_handler(meta)
        self.assertIs(meta.handler, handler)
        self.assertEqual(await meta.handler(), "loaded")

    async def test_runner_concurrency_and_restoration(self):
        class Registry:
            def get_handlers_by_event_type(self, *args, **kwargs):
                return []

        registry = Registry()
        sys.modules["astrbot.core.star.star_handler"].star_handlers_registry = registry

        class Runner:
            def __init__(self, name):
                self.run_context = SimpleNamespace(
                    context=SimpleNamespace(event=Event(name)),
                    messages=[{"role": "system", "content": name}],
                )
                self.req = request()
                self.provider = SimpleNamespace(provider_config={"id": "test"})

            def _func_tool_for_provider(self):
                return None

            async def _iter_llm_responses(self, **kwargs):
                yield Response(is_chunk=True)
                await asyncio.sleep(0)
                yield Response(
                    usage={"input_other": 10, "input_cached": 2, "output": 3}
                )

        sys.modules[
            "astrbot.core.agent.runners.tool_loop_agent_runner"
        ].ToolLoopAgentRunner = Runner
        original = Runner._iter_llm_responses
        self.observer.install()

        async def collect(name):
            return [item async for item in Runner(name)._iter_llm_responses()]

        results = await asyncio.gather(collect("one"), collect("two"))
        self.assertEqual([len(r) for r in results], [2, 2])
        for name in ("one", "two"):
            records = [r for r in self.records if r[0] == name]
            self.assertEqual(
                [r[1] for r in records], ["model_request", "model_response"]
            )
            self.assertEqual(records[0][2]["attempt_id"], records[1][2]["attempt_id"])
            self.assertEqual(records[0][2]["messages"][0]["content"], name)
        self.observer.uninstall()
        self.assertIs(Runner._iter_llm_responses, original)


class StorageTests(unittest.TestCase):
    def test_conversation_metadata_is_saved_and_available_in_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TraceStore(Path(tmp), {"persist_traces": True})
            event = Event("platform:GroupMessage:group_member")
            event.get_platform_id = lambda: "platform"
            event.is_private_chat = lambda: False
            event.get_group_id = lambda: "group"
            event.get_sender_name = lambda: "Member"
            event.message_obj = SimpleNamespace(
                group=SimpleNamespace(group_name="Example group")
            )
            store.record(event, "inbound", [{"json": {"text": "hello"}}])
            loaded = TraceStore(Path(tmp), {"persist_traces": True})
            summary = loaded.summaries()[0]
            self.assertEqual(summary["platform_id"], "platform")
            self.assertEqual(summary["chat_type"], "group")
            self.assertEqual(summary["group_id"], "group")
            self.assertEqual(summary["group_name"], "Example group")
            self.assertEqual(summary["sender_name"], "Member")

    def test_existing_database_adds_size_column_without_losing_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traces.sqlite3"
            db = sqlite3.connect(path)
            try:
                db.execute(
                    "CREATE TABLE traces (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE, body TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO traces(id, body) VALUES (?, ?)",
                    ("old", '{"id":"old","stages":[]}'),
                )
                db.commit()
            finally:
                db.close()
            store = TraceStore(Path(tmp), {"persist_traces": True})
            self.assertIsNone(store.error)
            self.assertEqual(store.detail("old")["id"], "old")
            store.record(Event(), "inbound", [{"json": {"text": "new"}}])
            self.assertIsNone(store.error)

    def test_snapshots_are_bounded_and_redact_known_keys(self):
        data = {
            "api_key": "secret",
            "nested": ["original"],
            "image": "data:image/png;base64,AAAA",
        }
        captured = observer_module.snapshot(data)
        data["nested"][0] = "changed"
        self.assertEqual(captured["nested"], ["original"])
        self.assertEqual(captured["api_key"], "[redacted]")
        self.assertEqual(captured["image"], "[omitted: inline media]")
        cyclic = []
        cyclic.append(cyclic)
        self.assertIn("nesting limit", str(observer_module.snapshot(cyclic)))

    def test_round_trip_detachment_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {"persist_traces": True, "max_persist_entries": 10}
            store = TraceStore(Path(tmp), cfg)
            event = Event()
            fields = [{"key": "detail", "json": {"text": "original"}}]
            store.record(event, "inbound", fields)
            fields[0]["json"]["text"] = "changed"
            trace_id = event.get_extra("_md_trace_id")
            loaded = TraceStore(Path(tmp), cfg)
            self.assertEqual(
                loaded.detail(trace_id)["stages"][0]["fields"][0]["json"]["text"],
                "original",
            )
            copy = loaded.detail(trace_id)
            copy["stages"].clear()
            self.assertEqual(len(loaded.detail(trace_id)["stages"]), 1)
            loaded.clear()
            self.assertEqual(TraceStore(Path(tmp), cfg).summaries(), [])

    def test_limits_are_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TraceStore(Path(tmp), {"persist_traces": False})
            event = Event()
            for _ in range(302):
                store.record(event, "inbound", [{"json": {"text": "x"}}])
            trace = store.detail(event.get_extra("_md_trace_id"))
            self.assertTrue(trace["truncated"])
            self.assertEqual(len(trace["stages"]), 300)


if __name__ == "__main__":
    unittest.main()
