# MsgDebugger

用于调试 AstrBot 主被动消息是否被其他插件有效处理，并提供**格式化管线日志**页面。

## 功能

1. **复读探针**：被动 `yield` 或主动 `send_message`，验证 MsgProcessor 等出站插件。
2. **管线日志**：记录入站 → LLM 请求 → **消息注入** → LLM 响应 → 出站装饰 → 已发送，消息内容按类型格式化展示。

## 查看日志

1. 启用插件，确保 `trace_enabled` 为真（默认开启）。
2. **重载插件**（首次添加 `pages/logs/` 后必须重载）。
3. 打开 AstrBot WebUI → 插件 → MsgDebugger → 打开 Page **`logs`**。
4. 发消息或触发 LLM 对话，页面每 3 秒自动刷新（可关）。

> 日志 Page 需要 AstrBot **>= 4.24.2**（Plugin Pages / `register_web_api`）。若加载失败，请确认 AstrBot 版本并重载插件。

页内可切换：

- **阶段**：入站 / LLM 请求 / **消息注入** / LLM 响应 / 出站 / 已发送
- **内容**：各字段独立开关（Prompt、System、消息链等）
- **选项**：差异高亮、长文本折叠、umo 过滤

开关保存在浏览器 `localStorage`，刷新后仍有效。

## 记录内容说明

| 阶段 | 主要内容 |
|------|----------|
| 入站 | `message_str`、消息链分段 `[Plain]` `[Image]` … |
| LLM 请求 | 注入完成后的 `prompt`（含 `<msg>` 拆解）、`system`、`extra` |
| **消息注入** | 命中规则、完整注入文本、Prompt/System 注入前后对比 |
| LLM 响应 | 回复文本、回复链、reasoning、token |
| 出站装饰 | 出站链、纯文本预览（对比 MsgProcessor） |
| 已发送 | 发送完成、复读模式 |

`on_llm_request` 在 priority `100` 快照注入前请求，在 priority `-100` 记录注入后结果，便于对比 InfoInjection 等插件效果。

## 配置

见 `_conf_schema.json`：`send_mode`、`echo_content`、白名单、`trace_enabled`、`max_trace_entries`。

## 开发

```bash
cd msgdebugger
python -c "from core.trace_store import build_inbound_fields; print('ok')"
```

新增或修改 `pages/logs/` 后需**重载插件**；仅改静态资源时刷新 Page 即可。
