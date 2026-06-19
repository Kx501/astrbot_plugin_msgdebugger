const STORAGE_KEY = "msgdebugger.logs.ui";

const STAGE_LABELS = {
  inbound: "入站",
  llm_request: "LLM 请求",
  llm_response: "LLM 响应",
  decorating: "出站装饰",
  sent: "已发送",
};

const FIELD_LABELS = {
  message_str: "原始文本",
  chain: "消息链",
  prompt: "Prompt",
  system: "System",
  extra_parts: "Extra 块",
  event_extras: "Event Extra",
  session_id: "Session",
  images: "图片",
  audios: "音频",
  completion: "回复文本",
  reasoning: "Reasoning",
  tokens: "Token",
  tools: "工具调用",
  plain: "纯文本预览",
  status: "状态",
  echo_mode: "调试复读",
  stopped: "事件终止",
};

const DEFAULT_UI = {
  stages: {
    inbound: true,
    llm_request: true,
    llm_response: true,
    decorating: true,
    sent: true,
  },
  fields: Object.fromEntries(Object.keys(FIELD_LABELS).map((k) => [k, true])),
  optDiff: false,
  optCollapse: true,
  autoRefresh: true,
  umoFilter: "",
};

const bridge = window.AstrBotPluginPage;
const traceList = document.getElementById("traceList");
const stageToggles = document.getElementById("stageToggles");
const fieldToggles = document.getElementById("fieldToggles");

let ui = loadUi();
let lastData = [];

function loadUi() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(DEFAULT_UI);
    return { ...structuredClone(DEFAULT_UI), ...JSON.parse(raw) };
  } catch {
    return structuredClone(DEFAULT_UI);
  }
}

function saveUi() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ui));
}

function renderToggle(container, entries, group) {
  container.innerHTML = "";
  for (const [key, label] of entries) {
    const id = `${group}-${key}`;
    const wrap = document.createElement("label");
    wrap.className = "inline";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = id;
    input.checked = ui[group][key] !== false;
    input.addEventListener("change", () => {
      ui[group][key] = input.checked;
      saveUi();
      renderTraces(lastData);
    });
    wrap.append(input, document.createTextNode(label));
    container.append(wrap);
  }
}

function setupToggles() {
  renderToggle(
    stageToggles,
    Object.entries(STAGE_LABELS),
    "stages",
  );
  renderToggle(
    fieldToggles,
    Object.entries(FIELD_LABELS),
    "fields",
  );
  const optDiff = document.getElementById("optDiff");
  const optCollapse = document.getElementById("optCollapse");
  const autoRefresh = document.getElementById("autoRefresh");
  const umoFilter = document.getElementById("umoFilter");

  optDiff.checked = ui.optDiff;
  optCollapse.checked = ui.optCollapse;
  autoRefresh.checked = ui.autoRefresh;
  umoFilter.value = ui.umoFilter || "";

  optDiff.addEventListener("change", () => {
    ui.optDiff = optDiff.checked;
    saveUi();
    renderTraces(lastData);
  });
  optCollapse.addEventListener("change", () => {
    ui.optCollapse = optCollapse.checked;
    saveUi();
    renderTraces(lastData);
  });
  autoRefresh.addEventListener("change", () => {
    ui.autoRefresh = autoRefresh.checked;
    saveUi();
  });
  umoFilter.addEventListener("input", () => {
    ui.umoFilter = umoFilter.value.trim();
    saveUi();
    renderTraces(lastData);
  });
}

function stagePlainText(stage) {
  const chunks = [];
  for (const field of stage.fields || []) {
    if (field.format === "lines") chunks.push((field.lines || []).join("\n"));
    else if (field.format === "prompt") chunks.push(field.prompt?.text || "");
    else if (field.format === "system") chunks.push(field.system?.text || "");
    else if (field.format === "extras") {
      chunks.push(
        (field.extras || []).map((row) => row.text || "").join("\n"),
      );
    } else if (field.format === "json") chunks.push(JSON.stringify(field.json || {}));
    else chunks.push(field.text || "");
  }
  return chunks.join("\n").trim();
}

function renderFieldBody(field, diff) {
  const wrap = document.createElement("div");
  wrap.className = "field-body" + (ui.optCollapse ? " collapsed" : "");
  if (diff) wrap.classList.add("diff");

  if (field.format === "lines") {
    wrap.textContent = (field.lines || []).join("\n") || "(空)";
  } else if (field.format === "prompt") {
    const p = field.prompt || {};
    if (p.kind === "msg_tag") {
      const attrs = document.createElement("div");
      attrs.className = "msg-tag-attrs";
      attrs.textContent = `<msg user="${p.attrs?.user || ""}" id="${p.attrs?.id || ""}">`;
      wrap.append(attrs, document.createElement("br"), document.createTextNode(p.body || ""));
    } else {
      wrap.textContent = p.text || "(空)";
    }
  } else if (field.format === "system") {
    const s = field.system || {};
    if (s.kind === "segments" && Array.isArray(s.segments)) {
      s.segments.forEach((seg) => {
        const block = document.createElement("div");
        block.className = "segment";
        block.textContent = seg;
        wrap.append(block);
      });
    } else {
      wrap.textContent = s.text || "(空)";
    }
  } else if (field.format === "extras") {
    (field.extras || []).forEach((row) => {
      const block = document.createElement("div");
      block.className = "segment";
      block.textContent = `${row.label || "extra"}: ${row.text || ""}`;
      wrap.append(block);
    });
  } else if (field.format === "json") {
    wrap.textContent = JSON.stringify(field.json || {}, null, 2);
  } else {
    wrap.textContent = field.text || "(空)";
  }

  const long =
    (wrap.textContent || "").length > 240 ||
    (field.lines || []).length > 4 ||
    (field.system?.segments || []).length > 2;
  if (long && ui.optCollapse) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "expand-btn";
    btn.textContent = "展开";
    btn.addEventListener("click", () => {
      const collapsed = wrap.classList.toggle("collapsed");
      btn.textContent = collapsed ? "展开" : "收起";
    });
    return { wrap, extra: btn };
  }
  return { wrap, extra: null };
}

function renderTraces(traces) {
  traceList.innerHTML = "";
  const needle = (ui.umoFilter || "").toLowerCase();
  const filtered = traces.filter((trace) => {
    if (!needle) return true;
    const hay = [
      trace.umo,
      trace.sender_id,
      trace.sender_name,
      trace.summary,
      trace.group_id,
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无记录。触发一条消息或 LLM 对话后刷新。";
    traceList.append(empty);
    return;
  }

  for (const trace of filtered) {
    const card = document.getElementById("traceTpl").content.firstElementChild.cloneNode(true);
    const head = card.querySelector(".trace-head");
    head.innerHTML = `
      <span class="time">${escapeHtml(trace.started_at || "")}</span>
      <span class="badge">${escapeHtml(trace.chat || "")}</span>
      <span class="badge">${escapeHtml(trace.sender_name || trace.sender_id || "")}</span>
      <span class="badge">${escapeHtml(shortUmo(trace.umo))}</span>
      <div class="summary">${escapeHtml(trace.summary || "")}</div>
    `;

    const stagesWrap = card.querySelector(".trace-stages");
    let prevText = "";

    for (const stage of trace.stages || []) {
      if (ui.stages[stage.key] === false) continue;

      const visibleFields = (stage.fields || []).filter(
        (field) => ui.fields[field.key] !== false,
      );
      if (!visibleFields.length) continue;

      const stageEl = document.createElement("section");
      stageEl.className = "stage";
      const title = document.createElement("div");
      title.className = "stage-title";
      title.textContent = `${STAGE_LABELS[stage.key] || stage.key} · ${stage.at || ""}`;
      stageEl.append(title);

      const currentText = stagePlainText(stage);
      const stageDiff = ui.optDiff && prevText && currentText !== prevText;

      for (const field of visibleFields) {
        const fieldEl = document.createElement("div");
        fieldEl.className = "field";
        const label = document.createElement("div");
        label.className = "field-label";
        label.textContent = field.label || FIELD_LABELS[field.key] || field.key;
        fieldEl.append(label);

        const fieldDiff =
          ui.optDiff &&
          stageDiff &&
          ["completion", "plain", "chain", "prompt"].includes(field.key);
        const { wrap, extra } = renderFieldBody(field, fieldDiff);
        fieldEl.append(wrap);
        if (extra) fieldEl.append(extra);
        stageEl.append(fieldEl);
      }

      stagesWrap.append(stageEl);
      if (currentText) prevText = currentText;
    }

    if (!stagesWrap.children.length) continue;
    traceList.append(card);
  }
}

function shortUmo(umo) {
  if (!umo) return "";
  return umo.length > 48 ? umo.slice(0, 45) + "..." : umo;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function apiGet(path) {
  const res = await bridge.apiGet(path);
  if (res && res.status === "ok" && res.data !== undefined) return res.data;
  return res || {};
}

async function fetchTraces() {
  const data = await apiGet("page/traces");
  lastData = data.traces || [];
  renderTraces(lastData);
}

async function clearTraces() {
  await bridge.apiPost("page/traces/clear", {});
  lastData = [];
  renderTraces([]);
}

document.getElementById("btnRefresh").addEventListener("click", fetchTraces);
document.getElementById("btnClear").addEventListener("click", clearTraces);

setupToggles();
await bridge.ready();
await fetchTraces();
setInterval(() => {
  if (ui.autoRefresh) fetchTraces().catch(console.error);
}, 3000);
