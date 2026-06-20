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

## 插件集成：Injection Trace 约定

MsgDebugger 对「谁在 LLM 请求里注入了什么」提供两层观测，**不要求**接入方依赖 MsgDebugger 包或 import 其代码。

### 观测层级

| 层级 | 机制 | 接入成本 |
|------|------|----------|
| **L0 通用 diff** | MsgDebugger 在 `on_llm_request` 前后对比 `ProviderRequest` | **零适配**：任意修改 `prompt` / `system_prompt` / `extra_user_content_parts` 的插件自动可见 |
| **L1 结构化报告** | 注入完成后 `event.set_extra(key, payload)` | 可选：在 logs 页展示规则 ID、注入块全文、位置等 |

L0 由 MsgDebugger 在 priority `100`（注入前快照）与 `-100`（注入后记录）完成，**接入方无需写任何 extra**。

L1 用于需要可读「命中了哪些规则、每块注入了什么」的场景；下文为 **MsgDebugger 对外约定的 payload 结构**（与具体业务插件解耦）。

### L1：结构化 extra

**推荐键名**：`_md_injection`

**遗留别名**：`_ii_injected`（同 schema；MsgDebugger 仍会读取，供旧版接入方兼容）

命名空间约定：`_md_` 前缀留给 MsgDebugger 生态；`_md_trace_id`、`_md_llm_before` 等为 MsgDebugger **内部自用**，第三方插件请勿写入。

#### Payload 结构

根对象：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | string | 否 | 报告来源，如插件名 `astrbot_plugin_xxx`，便于多插件并存时区分 |
| `date` | string | 否 | 业务日期标记（如每日注入的 `YYYY-MM-DD`） |
| `session_key` | string | 否 | 会话标识（可选，用于调试） |
| `rule_ids` | string[] | 否 | 本轮命中的规则 ID 列表（展示为「命中规则」） |
| `blocks` | object[] | **是**（L1 生效条件） | 注入块列表；**非空**时 logs 页展示结构化注入，否则仅显示「无结构化注入记录」 |

`blocks[]` 每项：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `rule_id` | string | 推荐 | 规则或块标识 |
| `position` | string | 推荐 | 注入位置，如 `system`、`message_start`、`message_end`、`extra` 等 |
| `ephemeral` | bool | 否 | `true` 表示仅本轮生效（UI 标为 temp） |
| `priority` | number | 否 | 排序/优先级（仅记录，不影响 MsgDebugger） |
| `text` | string | 推荐 | 注入全文；logs 页「注入块」直接展示 |
| `text_len` | number | 否 | 无 `text` 时可用长度占位，UI 显示 `(仅记录长度 N)` |

#### 写入时机

在 `on_llm_request` 钩子内，**完成对 `ProviderRequest` 的修改之后**调用 `event.set_extra(...)`。

MsgDebugger 在 priority `-100` 采集注入阶段，因此使用默认 priority 的 `on_llm_request` 钩子均在采集之前执行，无需为 MsgDebugger 单独调高/调低优先级。

#### 示例

```python
_INJECTION_EXTRA = "_md_injection"

@filter.on_llm_request()
async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
    # ... 修改 req.prompt / system_prompt / extra_user_content_parts ...

    if not applied_blocks:
        return

    event.set_extra(
        _INJECTION_EXTRA,
        {
            "source": "astrbot_plugin_your_name",
            "rule_ids": [b.rule_id for b in applied_blocks],
            "blocks": [
                {
                    "rule_id": b.rule_id,
                    "position": b.position,
                    "ephemeral": b.ephemeral,
                    "text": b.text,
                }
                for b in applied_blocks
            ],
        },
    )
```

#### L0 自动展示的 diff 字段

未提供 L1 或 `blocks` 为空时，若 `ProviderRequest` 仍被改动，注入阶段仍可能包含：

- `prompt_before` — Prompt 注入前快照
- `system_added` / `system_diff` — System 追加或变更
- `extra_added` — Extra 块新增内容

#### 注意

- `text` 会进入内存 trace 与 `traces.jsonl` 持久化，请勿写入密钥等敏感信息。
- 多插件同时注入时，各自可写独立 extra；合并展示策略后续版本可能扩展，当前以**单次 set_extra 覆盖**为准（后写覆盖先写）。
- 本约定仅描述 **logs 页可读性**；不改变 AstrBot 注入行为本身。

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
