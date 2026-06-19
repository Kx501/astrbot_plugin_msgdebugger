# -*- coding: utf-8 -*-
"""运行时开关（覆盖配置，重载插件后重置）。"""

from __future__ import annotations

import threading


class RuntimeFlags:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._echo: bool | None = None

    def echo_enabled(self, config_default: bool) -> bool:
        with self._lock:
            return config_default if self._echo is None else self._echo

    def set_echo(self, value: bool | None) -> None:
        with self._lock:
            self._echo = value

    def echo_status(self, config_default: bool) -> str:
        with self._lock:
            if self._echo is None:
                return f"配置默认（{'开' if config_default else '关'}）"
            return "开" if self._echo else "关"

    def snapshot(self, *, echo_cfg: bool) -> dict[str, str]:
        return {
            "echo": self.echo_status(echo_cfg),
            "echo_active": "开" if self.echo_enabled(echo_cfg) else "关",
        }


RUNTIME = RuntimeFlags()
