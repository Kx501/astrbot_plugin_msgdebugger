/* Exercise the actual page modules against both supported Pages response shapes. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import {trace,traces,fixtureReply} from './page_fixture.mjs';

class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.value=''; this.checked=true; this._text=''; }
  set textContent(value) { this._text=String(value); this.children=[]; }
  get textContent() { return this._text+this.children.map(c=>c.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text=''; this.children=children; }
  setAttribute() {}
  click() { return this.onclick?.(); }
}
const source=await fs.readFile(new URL('../pages/logs/app.js',import.meta.url),'utf8');
const uiSource=await fs.readFile(new URL('../pages/logs/ui.js',import.meta.url),'utf8');
const conversationSource=await fs.readFile(new URL('../pages/logs/conversation.js',import.meta.url),'utf8');
const descendants=node=>[node,...node.children.flatMap(descendants)];
for(const mode of ['unwrapped','envelope','error']) {
  const nodes=new Map(['#content','#tabs','#selection','#notice','#traces','#search','#refresh','#auto'].map(id=>[id,new Element('div')]));
  const calls=[];
  const reply=async(path,body)=>{
    calls.push(path);
    if(mode==='error')return {status:'error',message:'Specific backend failure'};
    const data=fixtureReply(path,body);
    return mode==='envelope'?{status:'ok',data}:data;
  };
  const context=vm.createContext({
    document:{createElement:tag=>new Element(tag),querySelector:id=>nodes.get(id),hidden:false},
    window:{AstrBotPluginPage:{ready:async()=>{},apiGet:reply,apiPost:reply}},
    setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref();return timer;},
    clearTimeout,setInterval:()=>0,structuredClone,console,
  });
  const ui=new vm.SourceTextModule(uiSource,{context});
  const app=new vm.SourceTextModule(source,{context});
  const conversation=new vm.SourceTextModule(conversationSource,{context});
  await app.link(specifier=>specifier==='./ui.js'?ui:conversation);
  await app.evaluate();
  if(mode==='error') {
    assert.match(nodes.get('#notice').textContent,/Specific backend failure/);
    continue;
  }
  assert.equal(nodes.get('#notice').textContent,'');
  assert.match(nodes.get('#selection').textContent,/今天新加坡/);
  const grouped=descendants(nodes.get('#traces')).filter(n=>n.className==='conversation-group');
  assert.equal(grouped.length,4,'same group merges members, but platforms/private/legacy remain separate');
  assert.equal(nodes.get('#tabs').children.length,8);
  for(const name of ['模型输入','插件改动','工具','Skills','请求对比','Token 与耗时','复读与采集','过程总览']) {
    const tab=nodes.get('#tabs').children.find(n=>n.textContent===name);
    await tab.onclick();
    assert.equal(nodes.get('#notice').textContent,'',`${mode}: ${name}`);
    assert.ok(nodes.get('#content').children.length,`${mode}: ${name} renders`);
    if(name==='模型输入') {
      const all=descendants(nodes.get('#content'));
      assert.equal(all.filter(n=>n.className==='message-reader').length,1);
      assert.ok(all.filter(n=>n.className?.startsWith('message-row')).length<=10);
      assert.match(all.find(n=>n.className==='message-reader').textContent,/#50 user/);
      assert.match(nodes.get('#content').textContent,/50 条输入消息/);
    }
    assert.match(nodes.get('#selection').textContent,/本记录流程/);
  }
  const rail=descendants(nodes.get('#selection')).find(n=>n.className==='journey');
  await rail.children.find(n=>n.textContent==='请求 2').onclick();
  assert.match(nodes.get('#content').textContent,/52 条输入消息/);
  await nodes.get('#tabs').children.find(n=>n.textContent==='工具').onclick();
  assert.match(nodes.get('#selection').textContent,/当前选中请求 2 \/ 2/);
  assert.ok(calls.includes('page/detail'));
  assert.ok(calls.includes('page/inventory'));
}
console.log('Pages smoke checks passed: unwrapped/enveloped responses, backend errors and all eight tabs.');
