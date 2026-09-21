import {el, card, raw, button, select, hint, dataOf} from './ui.js';
import {requestSkills} from './skills.js';
import {conversationGroup, buildJourney, overviewView, inputView} from './conversation.js';

const bridge = window.AstrBotPluginPage;
const tabs = [['overview','过程总览'],['input','模型输入'],['plugins','插件改动'],['tools','工具'],['skills','Skills'],['compare','请求对比'],['usage','Token 与耗时'],['settings','复读与采集']];
const labels = {inbound:'收到消息',request_snapshot:'准备模型请求',model_request:'请求模型',model_response:'模型返回',model_error:'模型请求异常',model_interrupted:'模型请求中断',plugin_change:'插件执行',tool_start:'调用工具',tool_end:'工具返回',llm_response:'Agent 输出',decorating:'发送前处理',sent:'发送完成',echo_start:'复读开始',echo_sent:'主动复读返回',echo_error:'复读失败',extension:'插件补充报告'};
const state = {traces:[], trace:null, tab:'overview', attempt:0, runtime:{}, inventory:null, left:null, leftAttempt:0, scope:'base', changesOnly:true, groupOpen:new Map(), groupPages:new Map(), messageIndex:null, messagePage:0, inputFilter:'all', inputQuery:'', guideOpen:false};
let busy = false;
let selectionVersion = 0;
const content = document.querySelector('#content');
const requests = trace => (trace?.stages || []).filter(s => s.key === 'model_request' && dataOf(s).attempt_id).map(dataOf);
const current = () => requests(state.trace)[state.attempt];

async function api(path, body) {
  if (!bridge?.apiGet) throw new Error('请从 AstrBot WebUI 的插件 Pages 打开此页面。');
  let timer;
  try {
    const result = await Promise.race([
      body === undefined ? bridge.apiGet('page/' + path) : bridge.apiPost('page/' + path, body),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('请求超时，请刷新重试。')), 12000); })
    ]);
    if (result?.status === 'error') throw new Error(result.message || '调试接口返回异常');
    // The Pages host normally unwraps the backend envelope before replying.
    if (result?.status === 'ok' && Object.hasOwn(result, 'data')) return result.data;
    if (result && typeof result === 'object') return result;
    throw new Error('调试接口没有返回有效数据，请重载插件后重新打开页面。');
  } finally { clearTimeout(timer); }
}

async function choose(id) {
  const version = ++selectionVersion;
  const result = await api('detail', {id});
  if (version !== selectionVersion) return;
  if(state.trace?.id !== id) {
    state.tab='overview';state.attempt=0;state.messageIndex=null;state.messagePage=0;state.inputFilter='all';state.inputQuery='';
  }
  state.trace = result.trace;
  state.attempt=Math.min(state.attempt,Math.max(0,requests(state.trace).length-1));
  state.left = null;
  renderList(); render();
}

async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const [listing, runtime] = await Promise.all([api('traces'),api('runtime')]);
    state.traces = listing.traces || [];
    state.runtime = runtime;
    renderList();
    if (!state.trace && state.traces.length) await choose(state.traces[0].id);
    // Keep expanded details and reading position stable. Refresh the selected record explicitly.
    if (state.tab === 'settings') render();
    document.querySelector('#notice').textContent = runtime.storage_error || '';
  } catch (error) { document.querySelector('#notice').textContent = error.message; }
  finally { busy = false; }
}

function renderList() {
  const node = document.querySelector('#traces'); node.replaceChildren();
  const query = document.querySelector('#search').value.toLowerCase();
  const groups=new Map();
  for(const trace of state.traces) {
    const group=conversationGroup(trace);
    if(!`${trace.summary} ${trace.sender_id} ${trace.sender_name} ${trace.umo} ${group.label} ${group.platform}`.toLowerCase().includes(query))continue;
    if(!groups.has(group.key))groups.set(group.key,{...group,traces:[]});
    groups.get(group.key).traces.push(trace);
  }
  for(const group of groups.values()) {
    const details=el('details',null,'conversation-group');
    details.open=!!query || (state.groupOpen.get(group.key) ?? (state.trace?conversationGroup(state.trace).key===group.key:groups.keys().next().value===group.key));
    details.ontoggle=()=>{state.groupOpen.set(group.key,details.open);};
    const title=el('summary');title.append(el('strong',group.label),el('small',`${group.platform} · ${group.traces.length} 条记录`));details.append(title);node.append(details);
    const page=Math.min(state.groupPages.get(group.key)||0,Math.ceil(group.traces.length/10)-1);
    for(const trace of group.traces.slice(page*10,page*10+10)) {
      const item=button('',()=>choose(trace.id),details);
      item.className='trace'+(state.trace?.id===trace.id?' active':'');
      item.append(el('strong',trace.summary||'无文本消息'),el('small',`${trace.started_at} · ${trace.sender_name||trace.sender_id}`));
    }
    if(group.traces.length>10) {
      const row=el('div',null,'toolbar');details.append(row);
      button('较新',()=>{state.groupPages.set(group.key,page-1);renderList();},row).disabled=page===0;
      row.append(el('small',`${page+1}/${Math.ceil(group.traces.length/10)}`));
      button('较早',()=>{state.groupPages.set(group.key,page+1);renderList();},row).disabled=(page+1)*10>=group.traces.length;
    }
  }
  if(!groups.size)node.append(el('p','没有符合条件的记录。发送消息后刷新。','muted'));
}

async function openView(key,attempt) {
  if(Number.isInteger(attempt)) {
    state.attempt=attempt;state.messageIndex=null;state.messagePage=0;state.inputFilter='all';state.inputQuery='';
  }
  await changeTab(key);
}

async function changeTab(key) {
  state.tab = key;
  render();
  if (['tools','skills'].includes(key) && !state.inventory) {
    state.inventory = await api('inventory');
    if (state.tab === key) render();
  }
  if (key === 'compare' && !state.left && state.trace) {
    const idx = state.traces.findIndex(t => t.id === state.trace.id);
    const previous = state.traces.slice(idx + 1).find(t => t.umo === state.trace.umo);
    if (previous) state.left = (await api('detail', {id:previous.id})).trace;
    else state.left = state.trace;
    state.leftAttempt = Math.max(0, requests(state.left).length - 1);
    if (state.tab === key) render();
  }
}

function requestPicker(parent) {
  const list = requests(state.trace);
  if (!list.length) { hint('没有逐轮模型请求记录。旧记录、第三方 Agent 或未启用的采集适配器可能没有此数据。',parent); return; }
  const row = el('div',null,'toolbar'); parent.append(row);
  select('模型请求',list.map((r,i) => [String(i),`第 ${i+1} 次 · ${r.provider || '未知提供商'} · ${r.model || '默认模型'}`]),String(state.attempt),v => openView(state.tab,Number(v)),row);
}

function render() {
  content.replaceChildren();content.className=state.tab;
  const nav = document.querySelector('#tabs'); nav.replaceChildren();
  for (const [key,title] of tabs) {
    const item = button(title,() => changeTab(key),nav);
    item.className = state.tab === key ? 'active' : '';
    item.setAttribute('aria-current',state.tab === key ? 'page' : 'false');
  }
  const selection = document.querySelector('#selection'); selection.replaceChildren();
  if (state.trace) {
    const heading=el('div',null,'selection-heading');selection.append(heading);
    heading.append(el('h2',state.trace.summary || '无文本消息'),el('small',`${conversationGroup(state.trace).label} · ${state.trace.started_at}`,'muted'));
    const actions = el('div',null,'toolbar selection-actions'); heading.append(actions);
    button('更新这条记录',() => choose(state.trace.id),actions);
    button('导出 / 脱敏预览',exportPreview,actions);
    const journey=el('div',null,'journey');journey.setAttribute('aria-label','本记录执行流程');selection.append(journey);
    journey.append(el('small','本记录流程','muted'));
    for(const [index,block] of buildJourney(state.trace).entries()) {
      if(index)journey.append(el('span','→','muted'));
      const item=button(block.title,()=>openView(block.kind==='request'?'input':'overview',block.attempt),journey);
      if(block.kind==='request'&&block.attempt===state.attempt)item.className='active';
    }
    if(current())selection.append(el('small',`当前选中请求 ${state.attempt+1} / ${requests(state.trace).length} · 输入 / 工具 / 对比共用；插件改动与用量看整条记录。`,'muted'));
    if (state.trace.truncated) hint('本记录触及采集上限，部分内容未保存。差异和用量可能不完整。',selection);
  } else selection.append(el('h2','等待第一条调试记录'));
  if (!state.trace && !['tools','skills','settings'].includes(state.tab)) {
    content.append(el('div','发送一条消息，然后在左侧选择记录。工具、Skills 和复读设置可直接查看。','empty')); return;
  }
  if (state.tab === 'overview') overview();
  if (state.tab === 'input') input();
  if (state.tab === 'plugins') plugins();
  if (state.tab === 'tools') tools();
  if (state.tab === 'skills') skills();
  if (state.tab === 'compare') compare();
  if (state.tab === 'usage') usage();
  if (state.tab === 'settings') settings();
}

function overview() {
  overviewView(state.trace,content,openView);
}

function input() {
  requestPicker(content);
  inputView(state.trace,current(),state,content,render,openView);
}

function plugins() {
  hint('“执行边界”表示在指定插件处理函数运行前后观察到变化；嵌套调用和共享状态并发修改可能也在这个区间。它不是逐行代码追踪。补充报告则由插件自行声明来源。',content);
  const row = el('div',null,'toolbar'); content.append(row);
  select('显示',[['changed','有改动或异常'],['all','所有已观测执行']],state.changesOnly?'changed':'all',v=>{state.changesOnly=v==='changed';render();},row);
  const stages = state.trace.stages.filter(s=>s.key==='extension'||(s.key==='plugin_change'&&(!state.changesOnly||dataOf(s).changed||dataOf(s).error)));
  if(!stages.length) content.append(el('div','此筛选下没有插件改动记录。未记录不代表插件没有运行。','empty'));
  for(const stage of stages) {
    const data=dataOf(stage);
    const box=card(data.source || data.report?.source || '来源未知',content);
    box.append(el('span',stage.key==='extension'?'插件自行报告':'执行边界观测','badge'));
    box.append(el('p',`${data.handler || ''} ${data.hook || ''}`));
    if(data.duration_ms!==undefined) box.append(el('small',`${data.duration_ms} ms`,'muted'));
    if(data.error) box.append(el('p',data.error,'bad'));
    if(data.changed) {
      const diff=el('details');diff.open=true;
      diff.append(el('summary','变化内容 · − 删除 / + 新增'));
      const pre=el('pre');diff.append(pre);box.append(diff);
      for(const line of data.diff?.lines || []) pre.append(el('span',line,'diff-line'+(line.startsWith('+')?' add':line.startsWith('-')?' remove':'')));
      if(!data.diff) hint('请重新打开这条记录以加载差异。',diff);
      if(data.diff?.truncated) hint('差异过长，已截断；请结合下方修改前后内容查看。',diff);
      for(const key of new Set([...Object.keys(data.before||{}),...Object.keys(data.after||{})])) {
        if(JSON.stringify(data.before?.[key])===JSON.stringify(data.after?.[key])) continue;
        raw(`${key} · 修改前`,data.before?.[key],box);
        raw(`${key} · 修改后`,data.after?.[key],box);
      }
    } else if(stage.key!=='extension') box.append(el('p','未观察到所采集字段变化。','muted'));
    if(data.yielded) raw('插件产出的结果',data.yielded,box);
    if(data.report) raw('补充报告',data.report,box);
  }
}

function tools() {
  requestPicker(content);
  hint('当前注册目录与历史请求快照分别展示。已注册 ≠ 本次提供 ≠ 实际调用。未匹配到注册插件时仅显示模块来源，不猜测所属插件。',content);
  const offered=current()?.tools || [];
  const called=(state.trace?.stages||[]).filter(s=>s.key==='tool_start').map(dataOf);
  const names=new Set(called.map(c=>c.tool?.name));
  const hasRequest=!!current();
  const list=hasRequest?offered:(state.inventory?.tools||[]);
  content.append(el('h2',hasRequest?`选中请求的工具快照 · ${offered.length} 个`:'当前注册工具'));
  if(!list.length) hint(hasRequest?'这次请求没有提供工具。已注册工具仍可在下方实时目录中查看。':state.inventory?'没有可显示的工具。':'正在加载工具目录…',content);
  for(const tool of list) {
    const box=card(tool.name,content);
    box.append(el('span',hasRequest?'本次提供':'当前注册','badge'));
    if(names.has(tool.name)) box.append(el('span','本次对话已调用','badge'));
    if(tool.active===false) box.append(el('span','未启用','badge'));
    box.append(el('p',tool.description),el('small',`来源：${tool.source}`,'muted'));
    raw('参数定义',tool.parameters,box);
  }
  raw('当前全部注册工具（实时目录）',state.inventory?.tools || [],content);
  for(const stage of (state.trace?.stages||[]).filter(s=>s.key==='tool_start'||s.key==='tool_end')) raw(`${labels[stage.key]} · ${dataOf(stage).tool?.name || ''}`,dataOf(stage),content);
  for(const error of state.inventory?.errors||[]) hint(error,content);
}

function skills() {
  requestPicker(content);
  const req=current();
  const offered=requestSkills(req?.messages || []);
  const list=state.inventory?.skills || [];
  const header=card(req?`本次请求携带的技能目录 · ${offered.length} 项`:'先选择一次模型请求',content);
  hint('“本次携带”从选中请求的 system / developer 技能目录提取，反映人格和配置筛选后的输入。目录进入请求不等于模型读取了 SKILL.md 全文，也不等于执行了技能。',header);
  if(req && !offered.length) hint('这份快照中没有识别到 AstrBot 标准技能目录。全部停用时这是正常的；自定义格式或被截断的目录暂时无法识别。',header);
  for(const skill of offered) {
    const box=card(skill.name,header);
    box.append(el('span',`本次携带 · 消息 #${skill.messageIndex+1}`,'badge'));
    box.append(el('p',skill.description),el('small',skill.path,'muted'));
  }
  const enabled=list.filter(s=>s.active===true).length;
  const catalog=card(`当前本地文件目录 · ${list.length} 项 / 技能开关开启 ${enabled} 项`,content);
  hint('技能开关和所属插件状态分别显示：插件停用或未注册时，即使技能开关开启，AstrBot 也会过滤该插件技能。人格、配置和运行环境还会继续筛选；沙箱及工作区文件可能不在本地目录中。停用技能仍保留在这里供检查。',catalog);
  button('刷新当前目录',async()=>{state.inventory=await api('inventory');render();},catalog);
  if(!list.length) hint(state.inventory?'当前没有可读取的 Skills。':'正在加载 Skills…',catalog);
  for(const skill of list) {
    const box=card(skill.name,catalog);
    box.append(el('span',skill.active===true?'技能开关：开':skill.active===false?'技能开关：关':'技能开关：未知','badge'));
    if(skill.plugin_name) box.append(el('span',skill.plugin_registered===false?'所属插件未注册':skill.plugin_active===false?'所属插件已停用':skill.plugin_active===true?'所属插件已启用':'所属插件状态未知，请刷新','badge'));
    box.append(el('p',skill.description),el('small',`来源：${skill.plugin_name||skill.source_label||skill.source_type} · ${skill.path}`,'muted'));
    raw('SKILL.md 当前内容',skill.content ?? skill.content_error ?? '没有本地文件',box);
  }
  for(const error of state.inventory?.errors||[]) hint(error,content);
}

function compare() {
  requestPicker(content);
  hint('默认比较同一会话的上一条记录，也可以手动选择。基础部分包含 system / developer、工具和额外内容；注入用户消息里的指令需要在“全部内容”中查看。',content);
  const row=el('div',null,'toolbar');content.append(row);
  const options=state.traces.map(t=>[t.id,`${t.started_at} · ${t.summary}`]);
  select('比较对象',[['','请选择记录'],...options],state.left?.id||'',async id=>{if(!id)return;state.left=(await api('detail',{id})).trace;state.leftAttempt=0;render();},row);
  select('对象请求',requests(state.left).map((r,i)=>[String(i),`第 ${i+1} 次 · ${r.provider||''}`]),String(state.leftAttempt),v=>{state.leftAttempt=Number(v);},row);
  select('范围',[['base','提示词与工具'],['all','全部内容']],state.scope,v=>{state.scope=v;},row);
  const output=el('div');content.append(output);
  button('显示差异',async()=>{
    const left=requests(state.left)[state.leftAttempt],right=current();
    if(!left||!right)throw new Error('两边都需要选择已采集的模型请求。');
    const result=await api('compare',{left:{trace_id:state.left.id,attempt_id:left.attempt_id},right:{trace_id:state.trace.id,attempt_id:right.attempt_id},scope:state.scope});
    output.replaceChildren();
    if(!result.lines.length)hint('所选范围没有变化。',output);
    const pre=el('pre');output.append(pre);
    for(const line of result.lines)pre.append(el('span',line,'diff-line'+(line.startsWith('+')?' add':line.startsWith('-')?' remove':'')));
    if(result.truncated)hint('差异超过 5000 行，仅显示前 5000 行。',output);
  },row);
}

function usage() {
  const list=requests(state.trace);
  const responses=state.trace.stages.filter(s=>s.key==='model_response').map(dataOf);
  const totals={input:0,output:0,cached:0};let reported=0;
  for(const req of list) {
    const response=responses.find(r=>r.attempt_id===req.attempt_id);
    const u=response?.response?.usage;
    const box=card(`请求 ${list.indexOf(req)+1} · ${req.provider||'未知提供商'}`,content);
    if(u) {
      const input=u.input ?? ((u.input_other||0)+(u.input_cached||0));
      reported++;totals.input+=input;totals.output+=u.output||0;totals.cached+=u.input_cached||0;
      box.append(el('p',`服务商回报：输入 ${input} · 输出 ${u.output??'未提供'} · 缓存输入 ${u.input_cached??'未提供'}`));
    } else box.append(el('p','服务商未提供用量；不会计为零。','muted'));
    box.append(el('p',`请求耗时：${response?.duration_ms ?? '未记录'} ms`));
    const segments={系统指令:[],用户消息:[],历史回复:[],工具结果:[],其他:[]};
    for(const m of req.messages||[]) (segments[{system:'系统指令',developer:'系统指令',user:'用户消息',assistant:'历史回复',tool:'工具结果'}[m.role]||'其他']).push(m);
    const estimates={};
    for(const [name,messages]of Object.entries(segments))estimates[name]=Math.ceil(JSON.stringify(messages).length/4);
    estimates.工具定义=Math.ceil(JSON.stringify(req.tools||[]).length/4);
    raw('内容分布粗估（序列化字符数 ÷ 4，非模型分词）',estimates,box);
  }
  const total=card('本次对话 · 已回报用量合计',content);
  total.append(el('p',reported?`输入 ${totals.input} · 输出 ${totals.output} · 缓存输入 ${totals.cached}（包含在输入中）`:'没有可汇总的服务商用量。'));
  hint(`${reported} / ${list.length} 次请求有用量记录。缺失、失败、截断及 Provider 内部重试可能使合计不完整。粗估不包含真实媒体计费，也不能用来确认账单或上下文容量。`,content);
}

function settings() {
  const r=state.runtime;
  const box=card('复读探针',content);
  box.append(el('p',`当前：${r.echo||'未知'} · ${r.send_mode==='proactive'?'主动发送':'被动回复'} · ${r.echo_content==='chain'?'完整消息链':'纯文本'}`));
  hint('被动回复会进入 AstrBot 回复处理流程；主动发送直接调用发送接口。群 / 用户白名单和发送方式在插件配置中设置。这里的开关是临时覆盖，重载后恢复配置。',box);
  const row=el('div',null,'toolbar');box.append(row);
  for(const [action,label]of [['on','开启复读'],['off','关闭复读'],['reset','恢复配置']])button(label,async()=>{state.runtime=await api('echo',{action});render();},row);
  const coverage=card('采集能力与边界',content);
  for(const [key,title]of [['handlers','插件执行边界'],['runner','内置 Agent 逐轮请求'],['wire_payload','最终 HTTP 请求报文']])coverage.append(el('p',`${r.coverage?.[key]?'已启用':'未覆盖'} · ${title}`));
  hint('仅采集启用之后发生的事件。插件私有后台任务、第三方 Agent、绕过 AstrBot 的网络请求、模型内部思考均不保证可见。插件名归因覆盖已包装的事件处理函数；并发 / 嵌套修改只证明发生在执行区间。',coverage);
  if(!r.trace_enabled)hint('日志采集已关闭，可在插件配置中开启并重载。',coverage);
  if(r.storage_error)hint(r.storage_error,coverage);
  hint('数据默认保存在本机。单阶段 256 KiB、单记录 2 MiB / 300 阶段，总内容约 64 MiB；触及上限会明确标记。已知密钥字段会隐藏，但聊天正文仍可能含隐私。',coverage);
  button('清空当前调试记录',async()=>{if(!window.confirm('清空当前内存及数据库中的调试记录？旧版 JSONL 备份会保留。'))return;await api('traces/clear',{});state.trace=null;state.left=null;await refresh();render();},coverage).className='danger';
}

function exportPreview() {
  const trace=structuredClone(state.trace);
  for(const key of ['umo','sender_id','sender_name','group_id','group_name','platform_id'])trace[key]='[已隐藏]';
  const text=JSON.stringify(trace,null,2).replace(/\bBearer\s+[A-Za-z0-9._~+\/-]+/gi,'Bearer [已隐藏]').replace(/\bsk-[A-Za-z0-9_-]{12,}/g,'[已隐藏密钥]');
  content.replaceChildren();
  content.append(el('h2','导出预览'));
  hint('已隐藏记录头部身份字段和部分常见密钥格式。正文、工具参数及路径仍可能包含个人信息，请检查后再分享。',content);
  raw('即将导出的内容',text,content,true);
  const row=el('div',null,'toolbar');content.append(row);
  button('下载此 JSON',()=>{
    const url=URL.createObjectURL(new Blob([text],{type:'application/json'}));
    const link=el('a');link.href=url;link.download=`msgdebugger-${trace.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  },row);
  button('返回',()=>render(),row);
}

document.querySelector('#refresh').onclick=refresh;
document.querySelector('#search').oninput=()=>{state.groupPages.clear();renderList();};
render();
try {
  if(bridge?.ready) await Promise.race([bridge.ready(),new Promise((_,reject)=>setTimeout(()=>reject(new Error('页面桥接初始化超时，请从插件 Pages 重新打开。')),12000))]);
  await refresh();
} catch(error) {document.querySelector('#notice').textContent=error.message;}
setInterval(()=>{if(!document.hidden&&document.querySelector('#auto').checked)refresh();},4000);
