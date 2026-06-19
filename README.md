# MsgDebugger

用于调试 AstrBot 主被动消息是否被其他插件有效处理，并提供**格式化管线日志**页面。

## 功能

1. **复读探针**：被动 `yield` 或主动 `send_message`，验证 MsgProcessor 等出站插件。
2. **管线日志**：记录入站 → LLM 请求 → 消息注入 → LLM 响应 → 出站装饰 → 已发送。
3. **抓包式持久化**：完整 trace 落盘，重载插件后仍可查看。
4. **运行时指令**：`/md echo on|off|status|reset` 临时控制复读（重载后恢复配置默认）。

## 指令

| 指令 | 说明 |
|------|------|
| `/md echo on\|off\|status\|reset` | 控制复读探针 |

`reset` 恢复为 WebUI 配置默认值。

## 查看日志

1. 启用插件，确保 `trace_enabled` / `persist_traces` 为真（默认开启）。
2. **重载插件**（首次添加或修改 `pages/logs/` 后必须重载）。
3. 打开 AstrBot WebUI → 插件 → MsgDebugger → Page **`logs`**。
4. 发消息或触发 LLM 对话；默认 **精简** 视图，可切换 **注入** / **完整**。

页内特性：

- **视图预设**：精简 / 注入 / 完整（顶栏单选）
- **筛选**：点击「筛选」展开阶段/字段/选项（原生 `<details>`）
- **Trace 卡片**：点击标题展开，阶段用 Tab 切换
- **自动刷新**：默认 3s；可勾选 1s；切走 tab 暂停，回来立即拉取

## 记录内容

| 阶段 | 主要内容 |
|------|----------|
| 入站 | 原始文本、消息链 |
| LLM 请求 | 注入后的 `prompt` / `system` / `extra` |
| 消息注入 | 命中规则、注入块、Prompt/System 增量（不重复 LLM 阶段全文） |
| LLM 响应 | 回复、token、工具调用 |
| 出站装饰 | 出站链、纯文本预览 |
| 已发送 | 发送状态、复读模式 |

`on_llm_request` 在 priority `100` 快照注入前，`-100` 记录注入后结果。

## 配置

见 `_conf_schema.json`：

- `echo_enabled` / `send_mode` / `echo_content` / 白名单
- `trace_enabled` / `persist_traces` / `max_persist_entries` / `max_trace_entries`

## 开发

```bash
cd msgdebugger
python -c "from core.trace_store import TraceStore; print('ok')"
```

新增或修改 `pages/logs/` 后需**重载插件**。
