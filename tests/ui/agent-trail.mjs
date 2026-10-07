import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const calls=[];
Object.assign(globalThis,{
  window,document,
  localStorage:{getItem:()=>null,setItem:()=>{}},
  location:{hash:'#/'},
  Event:window.Event,
  fetch:async url=>{calls.push(url);return {ok:true,status:200,json:async()=>({ok:true,events:[]})};},
});
window.requestAnimationFrame=callback=>callback();

const {state}=await import(root+'/public/state.js');
const {createAgentTrailView,renderAgentTrail}=await import(root+'/public/agent-trail.js');

const host=document.createElement('div');
renderAgentTrail(host,[
  {kind:'command',title:'Sign in to AWS',detail:'aws sso login',timestamp:'2026-10-07T08:00:00Z'},
  {kind:'memory',title:'Read memory',detail:'/memory/login-to-aws.md',resource:{type:'memory',id:'login-to-aws',label:'login-to-aws.md'}},
  {kind:'skill',title:'Use skill',resource:{type:'skill',id:'aws',label:'aws'}},
]);
assert.equal(host.querySelectorAll('.agenttrail-item').length,3,'one graphical card renders per structured action');
assert.equal(host.querySelector('.agenttrail-command .agenttrail-detail').textContent,'aws sso login');
assert.equal(host.querySelectorAll('button.agenttrail-resource').length,1,'memories are navigable while non-graph skill resources remain labels');
host.querySelector('button.agenttrail-resource').click();
assert.equal(location.hash,'#/memory/login-to-aws','a memory chip opens that node in the memory graph');

state.workspaceSlug='ticket-terminal';
const view=createAgentTrailView('OPS-1','codex');
assert.equal(view.shell.children[0],view.terminal);
assert.equal(view.trail.hidden,true);
view.setOpen(true);
await new Promise(resolve=>setTimeout(resolve,0));
assert(view.shell.classList.contains('agenttrail-open'),'the toggle switches the shared component into its 60/40 layout');
assert.equal(view.toggle.getAttribute('aria-pressed'),'true');
assert.equal(calls[0],'/api/agent-activity/OPS-1?provider=codex&w=ticket-terminal','activity requests retain workspace isolation');
view.shell.disposeAgentTrail();

console.log('agent-trail.mjs OK');
