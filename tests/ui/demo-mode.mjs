// Demo mode: a brand-new board (no tracker configured, no real tickets) shows
// a small fixed set of illustrative tickets instead of empty lanes — and the
// getting-started checklist that walks a new user from "just installed" to
// "actually using it." No browser: linkedom + a fetch stub keyed by path,
// same pattern as workspaces.mjs/lanes.mjs.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,location:{protocol:'http:',host:'localhost',hash:'#/'},confirm:()=>true,alert:()=>{},Event:window.Event,
  localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)}});
window.scrollTo=()=>{};
window.requestAnimationFrame=callback=>callback();
window.HTMLElement.prototype.scrollIntoView=()=>{};
Object.defineProperty(window.HTMLOptionElement.prototype,'selected',{configurable:true,
  get(){return this.hasAttribute('selected');},
  set(value){ value ? this.setAttribute('selected','') : this.removeAttribute('selected'); }});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});

let tickets={};
let categoryManagementState={ok:true,data:{revision:'r1',reviews:[],scan:{status:'ok'},
  onboarded:false,existingSetup:true,categories:[],history:[],role:'Software engineer',intervalHours:0,
  roles:['Software engineer'],presets:{'Software engineer':[]}}};
const body=(url,opts)=>{
  // state.jiraConfigured/notionConfigured are set directly in the tests below — reloadBoard()
  // itself never fetches /api/config (only loadWorkspaceBoard() does, which this test does not
  // call), so this endpoint is not on the path under test here.
  if(url.startsWith('/api/config')) return {jiraBaseUrl:'',jiraConfigured:false,notionConfigured:false};
  if(url.startsWith('/api/tickets')) return tickets;
  if(url.startsWith('/api/category-management')) return categoryManagementState;
  if(url.startsWith('/api/people')) return {};
  if(url.startsWith('/api/team-options')) return [];
  return {ok:true,statuses:[],priorities:[],doneStatuses:[],sprints:[],costs:{},usage:{},running:[],nodes:[],edges:[]};
};
globalThis.fetch=async(url,opts)=>({ok:true,status:200,json:async()=>body(url,opts)});
const settle=async()=>{for(let i=0;i<30;i++) await new Promise(resolve=>setTimeout(resolve,0));};

const {state}=await import(root+'/public/state.js');
const {buildCategoryUI}=await import(root+'/public/lanes.js');
const {reloadBoard}=await import(root+'/public/polling.js');
const {initCategoryManagement}=await import(root+'/public/category-management.js');

state.categories=[
  {id:'infra',name:'Infrastructure',status:'gap',color:'#4E79A7',note:'',docs:[],memories:[],skills:[]},
  {id:'docs',name:'Documentation',status:'gap',color:'#59A14F',note:'',docs:[],memories:[],skills:[]},
];
buildCategoryUI();

// --- demo docs appear only with nothing real configured, and never otherwise ---
{
  state.jiraConfigured=false; state.notionConfigured=false; tickets={};
  await reloadBoard(); await settle();
  assert.equal(state.showingDemoDocs,true,'no tracker and no real tickets means demo mode is on');
  const lanesEl=document.getElementById('lanes');
  const demoBadges=[...lanesEl.querySelectorAll('.demobadge')];
  assert.equal(demoBadges.length,6,'the fixed 6-ticket demo set renders, one lane row each');
  assert.equal(document.getElementById('demoNotice').hidden,false,'the demo banner shows');

  state.jiraConfigured=true;
  await reloadBoard(); await settle();
  assert.equal(state.showingDemoDocs,false,'configuring a tracker turns demo mode off immediately');
  assert.equal(lanesEl.querySelectorAll('.demobadge').length,0);
  assert.equal(document.getElementById('demoNotice').hidden,true);

  state.jiraConfigured=false; state.notionConfigured=false; tickets={'OPS-1':{key:'OPS-1',summary:'Real ticket',categories:['infra'],jiraStatus:'Backlog',jiraPriority:'Medium'}};
  await reloadBoard(); await settle();
  assert.equal(state.showingDemoDocs,false,'one real ticket of any kind is enough to turn demo mode off, tracker or not');
  assert.equal(lanesEl.querySelectorAll('.demobadge').length,0);
  tickets={};
}

// --- every mutating control on a demo row is disabled, not wired -----------
{
  state.jiraConfigured=false; state.notionConfigured=false;
  await reloadBoard(); await settle();
  const row=[...document.querySelectorAll('.ticketrow')].find(r=>r.dataset.ticketKey==='DEMO-101');
  assert.ok(row,'DEMO-101 renders through the real ticket-row pipeline');
  assert.equal(row.querySelector('.statussel'),null,'no tracker means no live status options, so the existing read-only fallback already applies');
  const prioSel=row.querySelector('.prioritysel');
  assert.ok(prioSel && prioSel.disabled,'priority select is disabled on a demo row');
  assert.equal(row.querySelector('.categoryedit'),null,'category-edit is not rendered at all for a demo row');
  const mrInput=row.querySelector('.mrlinkinput');
  assert.ok(mrInput && mrInput.disabled,'MR-link input is disabled on a demo row');
  const noteInput=row.querySelector('.noteform input');
  assert.ok(noteInput && noteInput.disabled,'the notes input is disabled on a demo row');
  assert.ok(row.querySelector('.demoterminalnote'),'the terminal panel shows an explanatory note instead of Open Claude/Codex buttons');
  assert.equal(row.querySelector('.terminal-controls button'),null,'no real terminal buttons render at all for a demo row');
  const costBadge=[...row.querySelectorAll('.costbadge')].find(b=>!b.hidden);
  assert.ok(costBadge,'DEMO-101 carries the fake cost badge, through the exact same read-only badge code real tickets use');
}

// --- the demo set showcases nesting and linked tickets through the real pipeline ---
{
  const epicWrap=[...document.querySelectorAll('.epicchildrenwrap')];
  assert.ok(epicWrap.length>=1,'DEMO-103/104 render as a real epic+subtask group');
  const linkedLine=[...document.querySelectorAll('.linkedissueline')];
  assert.ok(linkedLine.length>=1,'DEMO-105/106 render the linked-tickets panel');
}

// --- getting-started checklist: live status, dismiss persists -------------
{
  categoryManagementState.data.onboarded=false;
  state.jiraConfigured=false; state.notionConfigured=false;
  await initCategoryManagement(); await settle();
  const gs=document.getElementById('gettingStarted');
  assert.equal(gs.hidden,false,'not onboarded and no tracker — checklist shows');
  const items=[...document.querySelectorAll('#gettingStartedList li')];
  assert.equal(items.filter(li=>li.className==='done').length,0,'nothing is done yet');
  assert.ok(items.some(li=>li.textContent.includes('Pick your work role')));
  assert.ok(items.some(li=>li.textContent.includes('Connect Jira or Notion')));
  assert.ok(items.some(li=>li.textContent.includes('Sign in')),'the CLI sign-in line is always shown, never as a checkmark');

  categoryManagementState.data.onboarded=true;
  state.jiraConfigured=true;
  await initCategoryManagement(); await settle();
  assert.equal(document.getElementById('gettingStarted').hidden,true,'fully onboarded (role picked + tracker connected) auto-hides the checklist');

  categoryManagementState.data.onboarded=false;
  state.jiraConfigured=false;
  await initCategoryManagement(); await settle();
  assert.equal(document.getElementById('gettingStarted').hidden,false,'back to not-done — it reappears, same as the existing role-reminder banner');
  document.getElementById('hideGettingStartedBtn').click();
  assert.equal(document.getElementById('gettingStarted').hidden,true,'"Hide this" dismisses it immediately');
  assert.equal(storage.get('wmp.hideGettingStarted'),'1','the dismissal is a localStorage preference, same convention as wmp.showNested etc.');
}

console.log('demo-mode.mjs OK');
// initCategoryManagement() starts a real setInterval poll (same as workspaces.mjs's note).
process.exit(0);
