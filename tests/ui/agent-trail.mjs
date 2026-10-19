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
  fetch:async url=>{calls.push(url);return {ok:true,status:200,json:async()=>url.startsWith('/api/manager-summary/') ? ({ok:true,brief:{
    requestedChange:'Allow the service role to invoke the alert Lambda.',
    architecture:'The geo-notifications service runs in Kubernetes and receives AWS permissions through a Terraform IAM module.',
    rationale:'A narrow invoke grant preserves least privilege and avoids changing the Lambda itself.',
    implementation:'The service role policy template gains permission for the publish-generic-alerts function.',
    rollout:'Promote through dev, staging, and production after the dev plan is clean.',
    status:'The code is ready, but deployment waits for the prerequisite IaC change to merge.',
  }}) : ({ok:true,events:[],summary:{
    headline:'Work recorded toward “Add comments”.',why:'Make ticket discussion visible.',
    facts:['Changed 2 named objects'],
    story:{request:'Add a manager-readable summary.',rationale:'The raw trail is too tactical for status reporting.',approach:'The agent grouped transcript evidence into a narrative and kept the detailed flow below it.',outcome:'Managers can now understand the work without reading terminal actions.'},
    flow:[{id:'investigate',label:'Investigate',detail:'Search files',count:2},{id:'change',label:'Make changes',detail:'Change app.js',count:1}],
    objects:[{type:'file',label:'app.js',path:'/repo/public/app.js',action:'update'}],
    knowledge:[{type:'memory',id:'jira-comments',label:'jira-comments.md'}],
  }})};},
});
window.requestAnimationFrame=callback=>callback();

const {state}=await import(root+'/public/state.js');
const {createAgentTrailView,renderAgentTrail,summarizeManager}=await import(root+'/public/agent-trail.js');

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

const fallback=summarizeManager([
  {kind:'search',title:'Search files'},
  {kind:'write',title:'Change app.js',resources:[{type:'file',label:'app.js',path:'/repo/app.js',action:'update'}]},
  {kind:'command',title:'Run command',detail:'npm test'},
],{key:'OPS-1',summary:'Add manager view',description:'Explain the work to a manager.'});
assert.equal(fallback.why,'Explain the work to a manager.','browser fallback uses ticket intent as the why');
assert.deepEqual(fallback.flow.map(step=>step.id),['investigate','change','verify'],'browser fallback preserves the evidence flow without new server code');
assert.equal(fallback.objects[0].label,'app.js');

state.workspaceSlug='ticket-terminal';
const view=createAgentTrailView('OPS-1','codex');
assert.equal(view.shell.children[0],view.terminal);
assert.equal(view.trail.hidden,true);
view.setOpen(true);
await new Promise(resolve=>setTimeout(resolve,0));
assert(view.shell.classList.contains('agenttrail-open'),'the toggle switches the shared component into its 60/40 layout');
assert.equal(view.toggle.getAttribute('aria-pressed'),'true');
assert.equal(calls[0],'/api/agent-activity/OPS-1?provider=codex&w=ticket-terminal','activity requests retain workspace isolation');
view.summaryToggle.click();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.summaryFeed.hidden,false,'manager summary opens in the same 60/40 evidence panel');
assert.equal(calls.filter(url=>url.startsWith('/api/manager-summary/')).length,1,'the expensive synthesis runs once when manager summary opens');
assert(calls.includes('/api/manager-summary/OPS-1?provider=codex&w=ticket-terminal'),'manager synthesis retains workspace isolation');
assert.deepEqual([...view.summaryFeed.querySelectorAll('.managerstory-section .managersummary-label')].map(node=>node.textContent),['The request','Architecture and scope','Why this approach','What changes where','Rollout and safety','Current state']);
assert.equal(view.summaryFeed.querySelectorAll('.managerstory-section p')[1].textContent,'The geo-notifications service runs in Kubernetes and receives AWS permissions through a Terraform IAM module.','the summary leads with architecture rather than an action grocery list');
assert.equal(view.summaryFeed.querySelectorAll('.managerflow-node').length,2,'the manager view retains a collapsed graphical evidence flow');
assert.equal(view.summaryFeed.querySelector('.managersummary-evidence').hasAttribute('open'),false,'supporting action evidence is collapsed at a glance');
await view.refresh();
assert.equal(view.summaryFeed.querySelectorAll('.managerstory-section p')[1].textContent,'The geo-notifications service runs in Kubernetes and receives AWS permissions through a Terraform IAM module.','activity polling does not overwrite the synthesized brief');
assert.equal(view.summaryFeed.querySelector('.managerobject-copy strong').textContent,'app.js','changed objects are named');
view.summaryFeed.querySelector('button.agenttrail-resource').click();
assert.equal(location.hash,'#/w/ticket-terminal/memory/jira-comments','manager knowledge chips retain workspace-scoped memory-graph navigation');
view.shell.disposeAgentTrail();

console.log('agent-trail.mjs OK');
