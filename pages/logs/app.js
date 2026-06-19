const STORAGE_KEY = "msgdebugger.logs.ui";

const STAGE_LABELS = {
  inbound: "入站",
  llm_request: "LLM",
  injection: "注入",
  llm_response: "回复",
  decorating: "出站",
  sent: "完成",
};

const FIELD_LABELS = {
  message_str: "文本",
  chain: "消息链",
  prompt: "Prompt",
  system: "System",
  extra_parts: "Extra",
  event_extras: "Extra元",
  session_id: "Session",
  images: "图片",
  audios: "音频",
  injection_rules: "规则",
  injection_blocks: "注入块",
  injection_date: "注入日",
  injection_status: "状态",
  prompt_before: "Prompt前",
  system_added: "Sys+",
  system_diff: "SysΔ",
  extra_added: "Extra+",
  completion: "回复",
  reasoning: "Reason",
  tokens: "Token",
  tools: "工具",
  plain: "纯文本",
  status: "状态",
  echo_mode: "复读",
  stopped: "终止",
};

const PRESETS = {
  compact: {
    label: "精简",
    stages: {
      inbound: true,
      llm_request: false,
      injection: true,
      llm_response: true,
      decorating: true,
      sent: false,
    },
    fields: {
      message_str: true,
      chain: false,
      prompt: false,
      system: false,
      extra_parts: false,
      event_extras: false,
      session_id: false,
      images: false,
      audios: false,
      injection_rules: true,
      injection_blocks: true,
      injection_date: false,
      injection_status: true,
      prompt_before: true,
      system_added: true,
      system_diff: true,
      extra_added: true,
      completion: true,
      reasoning: false,
      tokens: false,
      tools: false,
      plain: true,
      status: false,
      echo_mode: false,
      stopped: false,
    },
  },
  injection: {
    label: "注入",
    stages: {
      inbound: false,
      llm_request: true,
      injection: true,
      llm_response: false,
      decorating: false,
      sent: false,
    },
    fields: {
      message_str: false,
      chain: false,
      prompt: true,
      system: true,
      extra_parts: true,
      event_extras: false,
      session_id: false,
      images: false,
      audios: false,
      injection_rules: true,
      injection_blocks: true,
      injection_date: true,
      injection_status: true,
      prompt_before: true,
      system_added: true,
      system_diff: true,
      extra_added: true,
      completion: false,
      reasoning: false,
      tokens: false,
      tools: false,
      plain: false,
      status: false,
      echo_mode: false,
      stopped: false,
    },
  },
  full: {
    label: "完整",
    stages: Object.fromEntries(Object.keys(STAGE_LABELS).map((k) => [k, true])),
    fields: Object.fromEntries(Object.keys(FIELD_LABELS).map((k) => [k, true])),
  },
};

const DEFAULT_UI = {
  preset: "compact",
  stages: { ...PRESETS.compact.stages },
  fields: { ...PRESETS.compact.fields },
  optDiff: false,
  optCollapse: true,
  autoRefresh: true,
  fastRefresh: false,
  filtersOpen: false,
  umoFilter: "",
};

const bridge = window.AstrBotPluginPage;
const traceList = document.getElementById("traceList");
const stageToggles = document.getElementById("stageToggles");
const fieldToggles = document.getElementById("fieldToggles");
const presetRow = document.getElementById("presetRow");
const filterPanel = document.getElementById("filterPanel");
const runtimeBadge = document.getElementById("runtimeBadge");

let ui = loadUi();
let lastData = [];
let refreshTimer = null;
const traceTabState = new Map();

function loadUi() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return structuredClone(DEFAULT_UI);
    const parsed = JSON.parse(raw);
    const merged = { ...structuredClone(DEFAULT_UI), ...parsed };
    merged.stages = { ...DEFAULT_UI.stages, ...(parsed.stages || {}) };
    merged.fields = { ...DEFAULT_UI.fields, ...(parsed.fields || {}) };
    return merged;
  } catch {
    return structuredClone(DEFAULT_UI);
  }
}

function saveUi() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ui));
}

function applyPreset(name) {
  const preset = PRESETS[name];
  if (!preset) return;
  ui.preset = name;
  ui.stages = { ...preset.stages };
  ui.fields = { ...preset.fields };
  saveUi();
  setupToggles();
  renderTraces(lastData);
}

function markCustomPreset() {
  ui.preset = "custom";
  saveUi();
  renderPresetButtons();
}

function renderPresetButtons() {
  presetRow.innerHTML = "";
  for (const [key, preset] of Object.entries(PRESETS)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-btn" + (ui.preset === key ? " active" : "");
    btn.textContent = preset.label;
    btn.addEventListener("click", () => applyPreset(key));
    presetRow.append(btn);
  }
  if (ui.preset === "custom") {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-btn active";
    btn.textContent = "自定义";
    btn.disabled = true;
    presetRow.append(btn);
  }
}

function renderToggle(container, entries, group) {
  container.innerHTML = "";
  for (const [key, label] of entries) {
    const wrap = document.createElement("label");
    wrap.className = "inline";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = ui[group][key] !== false;
    input.addEventListener("change", () => {
      ui[group][key] = input.checked;
      markCustomPreset();
      saveUi();
      renderTraces(lastData);
    });
    wrap.append(input, document.createTextNode(label));
    container.append(wrap);
  }
}

function setupToggles() {
  renderPresetButtons();
  renderToggle(stageToggles, Object.entries(STAGE_LABELS), "stages");
  renderToggle(fieldToggles, Object.entries(FIELD_LABELS), "fields");

  document.getElementById("optDiff").checked = ui.optDiff;
  document.getElementById("optCollapse").checked = ui.optCollapse;
  document.getElementById("autoRefresh").checked = ui.autoRefresh;
  document.getElementById("fastRefresh").checked = ui.fastRefresh;
  document.getElementById("umoFilter").value = ui.umoFilter || "";
  filterPanel.classList.toggle("collapsed", !ui.filtersOpen);
}

function bindToolbarEvents() {
  document.getElementById("optDiff").addEventListener("change", (e) => {
    ui.optDiff = e.target.checked;
    saveUi();
    renderTraces(lastData);
  });
  document.getElementById("optCollapse").addEventListener("change", (e) => {
    ui.optCollapse = e.target.checked;
    saveUi();
    renderTraces(lastData);
  });
  document.getElementById("autoRefresh").addEventListener("change", (e) => {
    ui.autoRefresh = e.target.checked;
    saveUi();
    scheduleRefresh();
    if (ui.autoRefresh) fetchTraces().catch(console.error);
  });
  document.getElementById("fastRefresh").addEventListener("change", (e) => {
    ui.fastRefresh = e.target.checked;
    saveUi();
    scheduleRefresh();
  });
  document.getElementById("umoFilter").addEventListener("input", (e) => {
    ui.umoFilter = e.target.value.trim();
    saveUi();
    renderTraces(lastData);
  });
  document.getElementById("btnToggleFilters").addEventListener("click", () => {
    ui.filtersOpen = !ui.filtersOpen;
    saveUi();
    filterPanel.classList.toggle("collapsed", !ui.filtersOpen);
  });
}

function stagePlainText(stage) {
  const chunks = [];
  for (const field of stage.fields || []) {
    if (field.format === "lines") chunks.push((field.lines || []).join("\n"));
    else if (field.format === "prompt") chunks.push(field.prompt?.text || "");
    else if (field.format === "system") chunks.push(field.system?.text || "");
    else if (field.format === "extras") {
      chunks.push((field.extras || []).map((row) => row.text || "").join("\n"));
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
    (wrap.textContent || "").length > 200 ||
    (field.lines || []).length > 3 ||
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

function visibleStages(trace) {
  const result = [];
  for (const stage of trace.stages || []) {
    if (ui.stages[stage.key] === false) continue;
    const fields = (stage.fields || []).filter((f) => ui.fields[f.key] !== false);
    if (fields.length) result.push({ stage, fields });
  }
  return result;
}

function renderTraces(traces) {
  traceList.innerHTML = "";
  const needle = (ui.umoFilter || "").toLowerCase();
  const filtered = traces.filter((trace) => {
    if (!needle) return true;
    const hay = [trace.umo, trace.sender_id, trace.sender_name, trace.summary, trace.group_id]
      .join(" ")
      .toLowerCase();
    return hay.includes(needle);
  });

  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无记录。发消息后点刷新，或开启自动刷新。";
    traceList.append(empty);
    return;
  }

  for (const trace of filtered) {
    const stages = visibleStages(trace);
    if (!stages.length) continue;

    const card = document.getElementById("traceTpl").content.firstElementChild.cloneNode(true);
    const head = card.querySelector(".trace-head");
    const tabsNav = card.querySelector(".stage-tabs");
    const panelsWrap = card.querySelector(".stage-panels");

    head.innerHTML = `
      <span class="time">${escapeHtml(trace.started_at || "")}</span>
      <span class="badge">${escapeHtml(trace.chat || "")}</span>
      <span class="badge">${escapeHtml(trace.sender_name || trace.sender_id || "")}</span>
      <span class="summary">${escapeHtml(trace.summary || "")}</span>
      <span class="expand-hint">▸</span>
    `;

    let activeKey = traceTabState.get(trace.id);
    if (!activeKey || !stages.some(({ stage }) => stage.key === activeKey)) {
      activeKey = stages[0].stage.key;
    }

    let prevText = "";
    for (const { stage, fields } of stages) {
      const panel = document.createElement("div");
      panel.className = "stage-panel" + (stage.key === activeKey ? " active" : "");

      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "stage-tab" + (stage.key === activeKey ? " active" : "");
      tab.textContent = STAGE_LABELS[stage.key] || stage.key;
      tab.addEventListener("click", (e) => {
        e.stopPropagation();
        traceTabState.set(trace.id, stage.key);
        tabsNav.querySelectorAll(".stage-tab").forEach((el) => el.classList.remove("active"));
        panelsWrap.querySelectorAll(".stage-panel").forEach((el) => el.classList.remove("active"));
        tab.classList.add("active");
        panel.classList.add("active");
      });
      tabsNav.append(tab);

      const currentText = stagePlainText(stage);
      const stageDiff = ui.optDiff && prevText && currentText !== prevText;

      for (const field of fields) {
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
        panel.append(fieldEl);
      }

      panelsWrap.append(panel);
      if (currentText) prevText = currentText;
    }

    head.addEventListener("click", () => {
      card.classList.toggle("collapsed");
      const hint = head.querySelector(".expand-hint");
      if (hint) hint.textContent = card.classList.contains("collapsed") ? "▸" : "▾";
    });

    card.classList.add("collapsed");
    traceList.append(card);
  }
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

async function fetchRuntime() {
  try {
    const data = await apiGet("page/runtime");
    if (data && runtimeBadge) {
      runtimeBadge.textContent = `复读 ${data.echo_active || "?"} · 日志 ${data.trace_active || "?"}`;
    }
  } catch {
    /* ignore */
  }
}

async function clearTraces() {
  await bridge.apiPost("page/traces/clear", {});
  lastData = [];
  renderTraces([]);
}

function refreshIntervalMs() {
  return ui.fastRefresh ? 1000 : 3000;
}

function scheduleRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (!ui.autoRefresh || document.visibilityState !== "visible") return;
  refreshTimer = setInterval(() => {
    if (document.visibilityState === "visible") {
      fetchTraces().catch(console.error);
      fetchRuntime().catch(console.error);
    }
  }, refreshIntervalMs());
}

document.getElementById("btnRefresh").addEventListener("click", () => {
  fetchTraces().catch(console.error);
  fetchRuntime().catch(console.error);
});
document.getElementById("btnClear").addEventListener("click", clearTraces);

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    fetchTraces().catch(console.error);
    fetchRuntime().catch(console.error);
    scheduleRefresh();
  } else if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
});

setupToggles();
bindToolbarEvents();
await bridge.ready();
await fetchTraces();
await fetchRuntime();
scheduleRefresh();
