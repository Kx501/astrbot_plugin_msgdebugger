/* Synthetic data shared by page checks and the isolated visual preview. */
const stage=(key,data)=>({key,at:'2026-09-19 12:00:00',fields:[{key:'detail',json:data}]});
const history=[{role:'system',content:'你是群里的知识助手。回答简洁，遇到实时问题先使用工具。'}];
for(let i=1;i<=24;i++)history.push({role:'user',content:`历史问题 ${i}：这是以前聊过的内容。`},{role:'assistant',content:`历史回答 ${i}：这是以前模型说过的话。`});
history.push({role:'user',content:'今天新加坡天气怎么样？\n[附加上下文] 当前时间：2026-09-19。'});
const tool={name:'weather',description:'查询城市天气',source:'weather_plugin',parameters:{type:'object',properties:{city:{type:'string'}}}};
const first={attempt_id:'attempt-1',provider:'example-provider',messages:history,tools:[tool]};
const second={...first,attempt_id:'attempt-2',messages:[...history,{role:'assistant',content:null,tool_calls:[{id:'call-1',type:'function',function:{name:'weather',arguments:'{"city":"Singapore"}'}}]},{role:'tool',tool_call_id:'call-1',content:'示例数据：多云，28°C。'}]};
export const trace={id:'trace',started_at:'2026-09-19 12:00',platform_id:'qq-main',chat_type:'group',group_id:'123',group_name:'开发交流群',sender_id:'user-1',sender_name:'小明',umo:'qq-main:GroupMessage:123_user-1',summary:'今天新加坡天气怎么样？',stages:[
  stage('inbound',{text:'今天新加坡天气怎么样？'}),
  stage('plugin_change',{source:'context_plugin',changed:true,handler:'on_request',before:{request:{system_prompt:'基础指令'}},after:{request:{system_prompt:'基础指令 + 当前时间'}}}),
  stage('model_request',first),stage('model_response',{attempt_id:'attempt-1',duration_ms:420,response:{tools_call_name:['weather'],usage:{input_other:300,input_cached:40,output:20}}}),
  stage('tool_start',{tool,arguments:{city:'Singapore'}}),stage('tool_end',{tool,result:{text:'示例数据：多云，28°C。'}}),
  stage('model_request',second),stage('model_response',{attempt_id:'attempt-2',duration_ms:380,response:{_completion_text:'新加坡今天多云，约 28°C。',usage:{input_other:320,input_cached:40,output:25}}}),
  stage('llm_response',{response:{_completion_text:'新加坡今天多云，约 28°C。'}}),stage('decorating',{result:{text:'新加坡今天多云，约 28°C。'}}),stage('sent',{result:{text:'新加坡今天多云，约 28°C。'}})
]};
export const traces=[trace,
  {...trace,id:'trace-2',sender_id:'user-2',sender_name:'小红',umo:'qq-main:GroupMessage:123_user-2',summary:'同一个群的另一位成员'},
  {...trace,id:'trace-3',chat_type:'private',group_id:'',group_name:'',sender_name:'小林',umo:'qq-main:FriendMessage:user-1',summary:'私聊里的一次提问'},
  {...trace,id:'trace-4',platform_id:'qq-secondary',umo:'qq-secondary:GroupMessage:123_user-1',summary:'另一平台实例的同号群'},
  {...trace,id:'legacy',chat_type:undefined,platform_id:undefined,group_id:undefined,umo:'legacy:GroupMessage:unknown',summary:'缺少归属信息的旧记录'}
];
export function fixtureReply(path,body) {
  const name=path.split('/').at(-1);
  if(name==='traces')return {traces:traces.map(t=>({...t,stages:undefined,stage_count:t.stages.length}))};
  if(name==='detail')return {trace:traces.find(t=>t.id===body?.id)||trace};
  if(name==='runtime')return {echo:'关',trace_enabled:true,coverage:{handlers:true,runner:true}};
  if(name==='inventory')return {tools:[tool],skills:[],errors:[]};
  if(name==='compare')return {lines:[],truncated:false};
  if(name==='echo')return {echo:'开',coverage:{}};
  throw new Error('Unknown fixture route: '+path);
}
