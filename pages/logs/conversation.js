import {el, card, raw, button, select, hint, dataOf} from './ui.js';

export const roles = {system:'system · 全局指令',developer:'developer · 应用指令',user:'user · 输入材料',assistant:'assistant · 模型发言',tool:'tool · 工具返回'};
const meanings = {
  system:'告诉模型如何工作，例如人格、规则、技能目录。通常放在前面，但请以左侧实际顺序为准。',
  developer:'应用提供的行为要求。有些 API 使用这个角色；没有它也是正常的。',
  user:'输入给模型的问题或材料。AstrBot 也可能在这里拼接时间、引用、插件附加内容，所以不一定全是用户亲手输入的文字。',
  assistant:'模型一方的发言。出现在请求里时，它是被带回来的上下文，可能是以前的回复，也可能是要求调用工具；不是这次请求刚生成的答案。',
  tool:'程序执行工具后交回的结果。模型通常要在下一次请求里读到它，才能据此继续回答。'
};

export function conversationGroup(trace) {
  const platform = trace.platform_id || String(trace.umo || '').split(':')[0] || '未知平台';
  if(trace.chat_type==='group' && trace.group_id) return {key:JSON.stringify([platform,'group',trace.group_id]),label:`群聊 · ${trace.group_name || trace.group_id}`,platform};
  if(trace.chat_type==='private' && trace.sender_id) return {key:JSON.stringify([platform,'private',trace.sender_id]),label:`私聊 · ${trace.sender_name || trace.sender_id}`,platform};
  // Legacy sessions may encode group/member combinations; do not guess their identity.
  return {key:JSON.stringify(['legacy',trace.umo || trace.id]),label:`旧记录 · ${trace.umo || '未知会话'}`,platform};
}

export function buildJourney(trace) {
  const blocks=[];let attempt=-1;
  for(const stage of trace?.stages || []) {
    let last=blocks.at(-1);
    if(stage.key==='model_request') {
      const req=dataOf(stage);
      if(req.attempt_id)attempt++;
      last={kind:'request',title:req.attempt_id?`请求 ${attempt+1}`:'请求快照缺失',attempt:req.attempt_id?attempt:null,request:req,stages:[]};
      blocks.push(last);
    } else if(['llm_response','decorating','sent','echo_sent','echo_error'].includes(stage.key) && last?.kind!=='finish') {
      last={kind:'finish',title:'回复与发送',stages:[]};blocks.push(last);
    } else if(!last) {
      last={kind:'prepare',title:'收到消息 → 准备输入',stages:[]};blocks.push(last);
    }
    last.stages.push(stage);
  }
  return blocks;
}

export function overviewView(trace,parent,open) {
  const stages=trace.stages || [];
  const blocks=buildJourney(trace);
  const requests=blocks.filter(b=>b.kind==='request');
  const inbound=stages.find(s=>s.key==='inbound');
  const replies=stages.filter(s=>s.key==='llm_response'||s.key==='model_response');
  const final=dataOf(replies.at(-1)).response;
  const start=card('从这里开始：这一条消息发生了什么',parent);
  start.append(el('p',`收到「${String(dataOf(inbound).text || trace.summary || '无文本消息').slice(0,180)}」后，已观测到 ${requests.length} 次模型请求、${stages.filter(s=>s.key==='tool_start').length} 次工具执行。`));
  const changed=[...new Set(stages.filter(s=>s.key==='plugin_change'&&dataOf(s).changed).map(s=>dataOf(s).source))];
  if(changed.length) start.append(el('p',`这些插件执行期间有改动：${changed.join('、')}。`));
  const reply=final?._completion_text || (final?.result_chain?.chain || []).filter(p=>p.type==='Plain'||p.type==='plain'||p.text).map(p=>p.text||'').join('');
  if(reply) raw('最后观测到的模型回复',reply,start);
  const sent=stages.some(s=>s.key==='sent'||s.key==='echo_sent');
  start.append(el('p',sent?'已观测到发送通知 / 主动发送返回。':'尚未观测到发送完成：可能仍在执行，也可能未覆盖该路径。','muted'));
  const steps=el('div',null,'toolbar');start.append(steps);
  button('① 看模型收到什么',()=>open('input',0),steps);
  button('② 找哪个插件改了内容',()=>open('plugins'),steps);
  button('③ 比较两次请求',()=>open('compare'),steps);
  hint('下面按采集顺序串起整条记录。一次请求可以携带几十条历史消息；只有再次调用模型，才算下一次请求。',parent);
  for(const block of blocks) {
    const detail=el('details',null,'flow-block');
    const summary=el('summary');
    const parts=[];
    const changes=block.stages.filter(s=>s.key==='plugin_change'&&dataOf(s).changed);
    const calls=block.stages.filter(s=>s.key==='tool_start').map(s=>dataOf(s).tool?.name || '未知工具');
    if(block.kind==='request') {
      const response=block.stages.find(s=>['model_response','model_error'].includes(s.key));
      const d=dataOf(response);
      parts.push(`携带 ${block.request.messages?.length ?? '?'} 条消息`);
      if(d.error||d.response?.role==='err') parts.push('请求异常');
      else if(d.response?.tools_call_name?.length) parts.push(`模型要求调用 ${d.response.tools_call_name.join('、')}`);
      else parts.push(response?'模型返回内容':'尚无响应记录');
    }
    if(changes.length)parts.push(`${changes.length} 次插件改动`);
    if(calls.length)parts.push(`执行工具：${calls.join('、')}`);
    summary.append(el('strong',block.title),el('span',parts.join(' · ') || `${block.stages.length} 个已观测阶段`,'muted'));
    detail.append(summary);parent.append(detail);
    if(block.kind==='request')button('查看这次请求的输入',()=>open('input',block.attempt),detail);
    if(changes.length)button('查看插件改动',()=>open('plugins'),detail);
    for(const stage of block.stages) {
      const d=dataOf(stage);
      let title;
      if(stage.key==='plugin_change') {
        if(!d.changed&&!d.error)continue;
        title=`插件 ${d.source || '未知'} · ${d.changed?'改动了 '+Object.keys(d.after||{}).filter(k=>JSON.stringify(d.before?.[k])!==JSON.stringify(d.after?.[k])).join('、'):'执行异常'}`;
      } else title=({inbound:'收到原始消息',request_snapshot:'准备请求快照',model_request:'将输入交给模型',model_response:'收到模型响应',model_error:'模型请求异常',tool_start:'开始执行工具',tool_end:'收到工具结果',llm_response:'Agent 最终回复',decorating:'处理即将发送的消息',sent:'AstrBot 发出发送通知',echo_start:'开始复读',echo_sent:'主动复读返回',echo_error:'复读异常',extension:'插件补充报告'})[stage.key]||stage.key;
      if(d.tool?.name) title+=` · ${d.tool.name}`;
      raw(`${stage.at || ''} ${title}`,Object.keys(d).length?d:stage.fields,detail);
    }
  }
}

export function inputView(trace,req,state,parent,rerender,open) {
  const messages=Array.isArray(req?.messages)?req.messages:[];
  const lastUser=messages.reduce((found,m,i)=>m?.role==='user'?i:found,-1);
  const guide=el('details',null,'guide');
  guide.open=state.guideOpen;
  guide.ontoggle=()=>{state.guideOpen=guide.open;};
  guide.append(el('summary','第一次看 LLM 请求？先用一分钟理解角色、顺序与工具'));
  guide.append(el('p','AstrBot 把一份输入交给模型，模型再生成输出。你看到的 messages 是这份输入里的有序消息列表，列表有 50 项也可能只调用模型一次。历史内容通常会随请求再次发送，不能假定模型自动记得上次对话。'));
  const example=el('div',null,'example-flow');
  for(const text of ['system：你是简洁的助手','user：你好','assistant：你好！','user：帮我查天气','本次输出：assistant'])example.append(el('span',text));
  guide.append(el('p','请求里常见的 model 决定使用哪个模型，messages 是有序输入，tools 是可选工具目录。返回值包含模型生成的消息，服务商还可能报告 usage（Token 用量）。页面里的“输入”和“输出”对应这两个方向。'));
  guide.append(example,el('p','上例中，前四项一起作为输入；最后一项由本次调用生成。role 区分消息的用途和说话方，不代表它属于一个单独的请求。实际请求不必严格按 user / assistant 交替，左侧序号才是这条记录里的真实顺序。'));
  for(const [role,description]of Object.entries(meanings))guide.append(el('p',`${role}：${description}`));
  guide.append(el('p','tools 是另附的“可用工具目录”（名称、说明、参数），不是一次工具执行。模型返回 assistant 工具调用要求 → AstrBot 执行 → 结果写入 tool 消息 → 再请求模型。一次用户提问因此可能触发多次模型请求。'));
  parent.append(guide);
  if(!req) {
    hint('本记录没有逐轮请求快照。以下仅有插件钩子快照，不能补出完整调用顺序。',parent);
    for(const stage of trace.stages.filter(s=>s.key==='request_snapshot'))raw('请求准备阶段的数据',dataOf(stage),parent);
    return;
  }
  const top=el('div',null,'input-summary');
  top.append(el('strong',`一次请求 · ${messages.length} 条输入消息 · ${req.tools?.length || 0} 个可用工具`),el('span','序号是 messages 内的排列位置，不是模型调用次数。','muted'));
  parent.append(top);
  const allRequests=trace.stages.filter(s=>s.key==='model_request'&&dataOf(s).attempt_id).map(dataOf);
  const position=allRequests.findIndex(r=>r.attempt_id===req.attempt_id);
  const previousMessages=allRequests[position-1]?.messages;
  let common=0;
  if(previousMessages) {
    while(common<messages.length&&common<previousMessages.length&&JSON.stringify(messages[common])===JSON.stringify(previousMessages[common]))common++;
    top.append(el('span',common===messages.length&&common===previousMessages.length?'与上一请求的消息列表相同。':`与上一请求相比：前 ${common} 条一致，后 ${messages.length-common} 条可能新增或变化。`,'muted'));
  } else if(lastUser>0)top.append(el('span',`建议先读最后一条 user；前面的 ${lastUser} 条上下文收在目录里。`,'muted'));
  const shortcuts=el('div',null,'toolbar');parent.append(shortcuts);
  button('从最后一条 user 开始',()=>{state.inputFilter='all';state.inputQuery='';state.messageIndex=lastUser>=0?lastUser:0;state.messagePage=Math.floor(state.messageIndex/8);rerender();},shortcuts);
  if(previousMessages&&common<messages.length)button('定位本次新增 / 变化处',()=>{state.inputFilter='all';state.inputQuery='';state.messageIndex=common;state.messagePage=Math.floor(common/8);rerender();},shortcuts);
  button('只看全局指令',()=>{state.inputFilter='instructions';state.messageIndex=null;state.messagePage=0;rerender();},shortcuts);
  button(`查看工具目录（${req.tools?.length||0}）`,()=>open('tools'),shortcuts);
  const filters=el('div',null,'toolbar');parent.append(filters);
  select('消息范围',[['all','全部（原始顺序）'],['instructions','system / developer'],['user','user 输入材料'],['assistant','assistant 发言'],['tool','tool 工具结果']],state.inputFilter,v=>{state.inputFilter=v;state.messagePage=0;state.messageIndex=null;rerender();},filters);
  const search=el('input');search.type='search';search.placeholder='搜索消息内容，按 Enter';search.value=state.inputQuery;search.setAttribute('aria-label','搜索模型输入');
  search.onkeydown=event=>{if(event.key==='Enter'){state.inputQuery=search.value;state.messagePage=0;state.messageIndex=null;rerender();}};
  filters.append(search);
  const visible=messages.map((message,index)=>({message,index})).filter(({message})=>(state.inputFilter==='all'||(state.inputFilter==='instructions'?['system','developer'].includes(message?.role):message?.role===state.inputFilter))&&JSON.stringify(message).toLowerCase().includes(state.inputQuery.toLowerCase()));
  if(!visible.length){hint('没有符合筛选条件的消息。',parent);return;}
  if(state.messageIndex===null||!visible.some(v=>v.index===state.messageIndex)) {
    state.messageIndex=visible.some(v=>v.index===lastUser)?lastUser:visible[0].index;
    state.messagePage=Math.floor(visible.findIndex(v=>v.index===state.messageIndex)/8);
  }
  state.messagePage=Math.max(0,Math.min(state.messagePage,Math.ceil(visible.length/8)-1));
  const explorer=el('div',null,'message-explorer');parent.append(explorer);
  const directory=el('div',null,'message-directory');explorer.append(directory);
  directory.append(el('strong',`消息目录 · ${visible.length} 条`));
  for(const {message,index} of visible.slice(state.messagePage*8,state.messagePage*8+8)) {
    const row=button('',()=>{state.messageIndex=index;rerender();},directory);
    row.className='message-row'+(index===state.messageIndex?' active':'');
    row.setAttribute('aria-pressed',String(index===state.messageIndex));
    row.append(el('strong',`#${index+1} ${message?.role || '采集标记'}${index===lastUser?' · 最后一条 user':''}`));
    const preview=typeof message?.content==='string'?message.content:JSON.stringify(message?.content??message);
    row.append(el('small',preview.slice(0,90)||'无文本内容'));
  }
  const pagination=el('div',null,'toolbar');directory.append(pagination);
  button('上一页',()=>{state.messagePage--;rerender();},pagination).disabled=state.messagePage===0;
  pagination.append(el('small',`${state.messagePage+1} / ${Math.ceil(visible.length/8)}`));
  button('下一页',()=>{state.messagePage++;rerender();},pagination).disabled=(state.messagePage+1)*8>=visible.length;
  const index=state.messageIndex,message=messages[index];
  const reader=el('article',null,'message-reader');explorer.append(reader);
  reader.append(el('h3',`#${index+1} ${roles[message?.role] || '未知角色 / 采集标记'}`),el('p',meanings[message?.role] || '请查看原始结构以识别这个标记。','muted'));
  if(index===lastUser)reader.append(el('p','这是请求中最后一条 user，适合先看；它可能已混入插件附加材料，不能直接当作原始用户消息。','location-note'));
  const previous=messages[index-1],next=messages[index+1];
  reader.append(el('small',`排列位置：${previous?`#${index} ${previous.role || '未知'}`:'列表起点'} → 当前 → ${next?`#${index+2} ${next.role || '未知'}`:'列表终点，等待模型生成下一条输出'}`,'muted'));
  reader.append(el('pre',typeof message?.content==='string'?message.content:JSON.stringify(message?.content??message,null,2),'message-body'));
  if(message?.tool_calls?.length)raw('这条 assistant 要求执行的工具',message.tool_calls,reader,true);
  raw('这条消息的原始结构',message,reader);
  const response=trace.stages.find(s=>s.key==='model_response'&&dataOf(s).attempt_id===req.attempt_id);
  raw('本次调用生成的输出（不属于上面的输入列表）',response?dataOf(response).response:'尚未采集到对应响应',parent);
  const advanced=el('details',null,'advanced');advanced.append(el('summary','采集边界与完整原始数据'));parent.append(advanced);
  hint('这是 Provider 转换前快照，不是最终 HTTP 报文。模型能力过滤和格式转换仍可能改变它；序号顺序准确反映此处采集的列表。历史 / 当前内容的真实来源需结合插件改动判断。',advanced);
  raw('额外内容（可能已包含在消息里）',req.extra_user_content_parts,advanced);
  raw('完整请求快照',req,advanced);
}
