// Workspaces: one install, several boards, switched — never merged. What this
// pins down is that a one-workspace install is untouched (no picker, no `?w=`
// on the wire at all), that the workspace rides in the route so a pasted link
// carries it, that a bare route still means the default workspace, and that
// nothing anywhere shows two workspaces' data at once. No browser: linkedom
// plus a fetch stub that records every request.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
const location={protocol:'http:',host:'localhost',hash:''};
Object.assign(globalThis,{window,document,location,confirm:()=>true,alert:()=>{},Event:window.Event,
  localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)}});
window.scrollTo=()=>{};
// The memory graph draws with vis-network, a <script> global in the browser —
// stubbed to the surface renderMemoryGraph touches, since what is under test
// here is the route, not the drawing.
globalThis.vis={DataSet:class{constructor(items){this.items=items||[];}get(){return this.items;}},
  Network:class{constructor(){}on(){}once(){}off(){}fit(){}setOptions(){}selectNodes(){}focus(){}redraw(){}}};
window.requestAnimationFrame=callback=>callback();
// linkedom's HTMLOptionElement.selected doesn't reflect to the attribute its
// own getter reads, so a real browser's `option.selected = true` is a no-op
// here — back both it and the select's value by the attribute instead.
Object.defineProperty(window.HTMLOptionElement.prototype,'selected',{configurable:true,
  get(){return this.hasAttribute('selected');},
  set(value){ value ? this.setAttribute('selected','') : this.removeAttribute('selected'); }});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});

const categories=[{id:'api',name:'API',status:'gap',color:'#4E79A7',note:'',docs:[],memories:[],skills:[]}];
let registry={ok:true,defaultWorkspace:'dataflint',active:'dataflint',workspaces:[
  {slug:'dataflint',name:'DataFlint',createdAt:'2026-01-01',connected:true,ticketCount:12,lastSyncAt:'2026-09-15T08:00:00Z',syncing:false}]};
const calls=[];
const body=(url,opts)=>{
  if(url.includes('sync-if-stale')) return {ok:true,syncStarted:true,lastSyncAt:''};
  if(url.startsWith('/api/workspaces')) return opts&&opts.method==='POST'
    ? {ok:true,workspace:{slug:'ticket-terminal',name:'Ticket Terminal',createdAt:'2026-09-15'}} : registry;
  if(url.startsWith('/api/settings')) return {jira:{},notion:{connected:false},memoryDir:'/tmp/memory',memoryDirSource:'default'};
  if(url.startsWith('/api/categories')) return categories;
  if(url.startsWith('/api/config')) return {jiraBaseUrl:''};
  if(url.startsWith('/api/team-options')) return [];
  if(url.startsWith('/api/tickets')||url.startsWith('/api/people')) return {};
  if(url.startsWith('/api/category-management')) return {ok:true,data:{revision:'r1',reviews:[],scan:{status:'ok'},
    onboarded:true,existingSetup:true,categories:[],history:[],role:'Software engineer',intervalHours:0,
    roles:['Software engineer'],presets:{'Software engineer':[]}}};
  return {ok:true,statuses:[],priorities:[],doneStatuses:[],sprints:[],costs:{},usage:{},running:[],nodes:[],edges:[]};
};
globalThis.fetch=async(url,opts)=>{calls.push({url,opts}); return {ok:true,status:200,json:async()=>body(url,opts)};};
const settle=async()=>{for(let i=0;i<60;i++) await new Promise(resolve=>setTimeout(resolve,0));};
const urls=()=>calls.map(c=>c.url);

const {state}=await import(root+'/public/state.js');
const {apiJson,withWorkspace}=await import(root+'/public/api.js');
const ws=await import(root+'/public/workspaces.js');
const {renderRoute}=await import(root+'/public/router.js');

// ---- ?w= is added once, in apiJson, and only for a non-default workspace ----
state.workspaceSlug='';
assert.equal(withWorkspace('/api/tickets'),'/api/tickets','a bare route sends no workspace at all');
state.workspaceSlug='ticket-terminal';
assert.equal(withWorkspace('/api/tickets'),'/api/tickets?w=ticket-terminal');
assert.equal(withWorkspace('/api/categories?revision=abc'),'/api/categories?revision=abc&w=ticket-terminal',
  'a path that already carries a query string gets &w=, not a second ?');
assert.equal(withWorkspace('/api/workspaces/a-b/sync-if-stale'),'/api/workspaces/a-b/sync-if-stale?w=ticket-terminal');
calls.length=0;
await apiJson('/api/running-processes');
assert.equal(calls[0].url,'/api/running-processes?w=ticket-terminal','every call goes through the one choke point');
state.workspaceSlug='';
calls.length=0;
await apiJson('/api/running-processes');
assert.equal(calls[0].url,'/api/running-processes','…and a one-workspace install\'s traffic is unchanged');

// ---- the route carries the workspace; a bare route means the default --------
assert.deepEqual(ws.parseRoute('#/category/api'),{slug:'',path:'/category/api'});
assert.deepEqual(ws.parseRoute('#/w/ticket-terminal/category/api'),{slug:'ticket-terminal',path:'/category/api'});
assert.deepEqual(ws.parseRoute('#/w/ticket-terminal/memory/notes'),{slug:'ticket-terminal',path:'/memory/notes'});
assert.deepEqual(ws.parseRoute('#/w/ticket-terminal'),{slug:'ticket-terminal',path:'/'});
assert.deepEqual(ws.parseRoute(''),{slug:'',path:''});

state.defaultWorkspace='dataflint';
state.workspaceSlug='';
assert.equal(ws.routeHash('#/settings'),'#/settings','on the default workspace every pre-existing link is untouched');
assert.equal(ws.routeHash(''),'');
state.workspaceSlug='ticket-terminal';
assert.equal(ws.routeHash('#/settings'),'#/w/ticket-terminal/settings');
assert.equal(ws.routeHash('#/memory/x'),'#/w/ticket-terminal/memory/x');
assert.equal(ws.routeHash(''),'#/w/ticket-terminal','the board root of a named workspace');
assert.equal(ws.workspaceRouteHash('dataflint','/settings'),'#/settings','switching back to the default drops the prefix');
assert.equal(ws.activeWorkspaceSlug(),'ticket-terminal');
state.workspaceSlug='';
assert.equal(ws.activeWorkspaceSlug(),'dataflint','a bare route resolves through the registry\'s default');

// ---- one workspace renders no picker at all --------------------------------
const wrap=document.getElementById('workspaceWrap');
const sel=document.getElementById('workspaceSel');
calls.length=0;
await ws.loadWorkspaces();
await settle();
assert.equal(urls().filter(u=>u==='/api/workspaces').length,1);
assert.equal(state.defaultWorkspace,'dataflint');
assert.equal(wrap.hidden,true,'one workspace ⇒ no picker, no workspace chrome');
assert.equal(sel.children.length,0);

// ---- two workspaces render one ---------------------------------------------
registry={ok:true,defaultWorkspace:'dataflint',active:'dataflint',workspaces:[
  {slug:'dataflint',name:'DataFlint',createdAt:'2026-01-01',connected:true,ticketCount:12,lastSyncAt:'2026-09-15T08:00:00Z',syncing:false},
  {slug:'ticket-terminal',name:'Ticket Terminal',createdAt:'2026-09-15',connected:false,ticketCount:0,lastSyncAt:'',syncing:false}]};
await ws.loadWorkspaces();
await settle();
assert.equal(wrap.hidden,false,'two workspaces ⇒ the picker appears');
assert.deepEqual([...sel.options].map(o=>o.value),['dataflint','ticket-terminal','__new__']);
assert.deepEqual([...sel.options].map(o=>o.textContent),['DataFlint','Ticket Terminal','New workspace…']);
assert.equal(sel.value,'dataflint','the picker shows the workspace the board is on, not a merged anything');

// ---- a bare route resolves to the default workspace -------------------------
const settingsview=document.getElementById('settingsview');
const gridview=document.getElementById('gridview');
location.hash='#/settings';
renderRoute();
await settle();
assert.equal(state.workspaceSlug,'','a bare route leaves the board on the default workspace');
assert.equal(settingsview.classList.contains('hidden'),false,'…and still routes exactly as it did before workspaces existed');
calls.length=0;
await apiJson('/api/tickets');
assert.equal(calls[0].url,'/api/tickets','no ?w= is sent for the default workspace');

// ---- switching sets the route, reloads that workspace, and nudges its sync --
ws.wireWorkspaceUI();
calls.length=0;
sel.value='ticket-terminal';
sel.dispatchEvent(new window.Event('change'));
assert.equal(location.hash,'#/w/ticket-terminal','changing the picker sets the route — a pasted link carries the workspace');
renderRoute();
await settle();
assert.equal(state.workspaceSlug,'ticket-terminal');
assert(urls().includes('/api/categories?w=ticket-terminal'),'the switched-to workspace re-reads its own categories');
assert(urls().includes('/api/tickets?w=ticket-terminal'),'…and its own tickets');
assert(urls().every(u=>!/\bw=dataflint\b/.test(u)),'nothing is fetched from the workspace we left — workspaces are never merged');
const nudge=calls.find(c=>c.url.startsWith('/api/workspaces/ticket-terminal/sync-if-stale'));
assert(nudge&&nudge.opts.method==='POST','switching POSTs sync-if-stale for the new workspace');
assert.equal(gridview.classList.contains('hidden'),false,'…and lands on that workspace\'s board');

// A deep link into a named workspace routes to the view AND the workspace.
location.hash='#/w/dataflint/category/api';
renderRoute();
await settle();
assert.equal(state.workspaceSlug,'dataflint');
assert.equal(document.getElementById('detailview').classList.contains('hidden'),false,
  'the workspace prefix is stripped before the view patterns are matched');

// The memory graph (and its per-memory deep links) keeps working under a
// workspace prefix — the same pattern, matched against the stripped path.
location.hash='#/w/dataflint/memory';
renderRoute();
await settle();
assert.equal(document.getElementById('memoryview').classList.contains('hidden'),false,'#/w/<slug>/memory still opens the memory graph');
assert.equal(state.workspaceSlug,'dataflint');
location.hash='#/w/dataflint/category/api';
renderRoute();
await settle();

// Switching with a session open DETACHES it rather than refusing. Holding
// sessions in two workspaces at once is the reason this is one server process,
// and the server only forgets a process once it has exited — so the socket
// closes, the agent keeps running, and reopening the ticket reconnects.
let disposed=0;
// The real dispose calls ws.close(), whose close event — and so the onClose
// that releases the count — fires LATER. The late release below calls the REAL
// releaseTerminal, not a stub reimplementing it, so the test fails if the
// ownership guard is ever removed.
const {releaseTerminal}=await import(root+'/public/terminal-controller.js');
const panel={disposeTicketTerminal(){disposed++;}};
state.openTerminals.add(panel);
state.liveTerminalCount=1;
location.hash='#/w/ticket-terminal';
calls.length=0;
renderRoute();
await settle();
assert.equal(disposed,1,'the open terminal was let go of');
assert.equal(state.openTerminals.size,0);
assert.equal(state.liveTerminalCount,0,'the gate is settled synchronously, not left waiting on the close event');
assert.equal(state.workspaceSlug,'ticket-terminal','the switch goes through');
assert(urls().some(u=>u.includes('w=ticket-terminal')),'the new workspace is fetched');
assert.match(document.getElementById('dbstate').textContent,/left running in the background/,
  'and the board says the session survived rather than implying it was killed');

// A terminal opened in the NEW workspace, then the OLD one's socket finally
// closes. The late close must not steal the new terminal's count, or the next
// render would be unguarded and would destroy a live session.
const newPanel={disposeTicketTerminal(){}};
state.openTerminals.add(newPanel); state.liveTerminalCount=1;
assert.equal(releaseTerminal(panel),false,'the detached panel no longer owns a slot');
assert.equal(state.liveTerminalCount,1,'a late close from the workspace we left must not decrement the new one');
assert.equal(state.openTerminals.size,1);
state.openTerminals.clear(); state.liveTerminalCount=0;

// A board reload already in flight for the old workspace must not render over
// the new one. reloadBoard captures state.boardGeneration and drops its result
// when a switch has bumped it.
{
  const {reloadBoard}=await import(root+'/public/polling.js');
  const before=state.boardGeneration;
  let release; const gate=new Promise(r=>{release=r;});
  const realFetch=globalThis.fetch;
  globalThis.fetch=async(...a)=>{ await gate; return realFetch(...a); };
  const inflight=reloadBoard();
  state.boardGeneration++;            // a switch happens while it is in flight
  release();
  await inflight;
  globalThis.fetch=realFetch;
  assert.notEqual(state.boardGeneration,before);
  assert.doesNotMatch(document.getElementById('dbstate').textContent||'',/data\/db\.json/,
    'the stale reload did not claim to have rendered the board');
}

// Back to the first workspace for the rest of the suite.
location.hash='#/w/dataflint';
renderRoute();
await settle();

// ---- creating one ----------------------------------------------------------
state.workspaceSlug='';
ws.renderWorkspacesForm();
const form=document.querySelector('#settingsWorkspacesForm form');
const slugInput=document.getElementById('newWorkspaceSlug');
const nameInput=document.getElementById('newWorkspaceName');
const msg=document.getElementById('newWorkspaceMsg');

slugInput.value='Not A Slug';
nameInput.value='Nope';
calls.length=0;
form.dispatchEvent(new window.Event('submit'));
await settle();
assert.equal(calls.length,0,'a bad slug is never POSTed');
assert(msg.textContent.includes('lowercase'));

slugInput.value='default';
form.dispatchEvent(new window.Event('submit'));
await settle();
assert.equal(calls.length,0);
assert(msg.textContent.includes('reserved'),'"default" is reserved');

slugInput.value='ticket-terminal';
nameInput.value='Ticket Terminal';
form.dispatchEvent(new window.Event('submit'));
await settle();
const created=calls.find(c=>c.url.startsWith('/api/workspaces')&&c.opts&&c.opts.method==='POST');
assert(created,'the form POSTs /api/workspaces');
assert.deepEqual(JSON.parse(created.opts.body),{slug:'ticket-terminal',name:'Ticket Terminal'});
assert.equal(location.hash,'#/w/ticket-terminal/settings',
  'a new workspace is switched to and lands on its own Settings page with nothing connected');

console.log('PASS: workspaces — no picker with one workspace, one with two; the route carries the slug and a bare route means the default; ?w= added once in apiJson; switching reloads only the new workspace and nudges its sync; switching detaches live terminals without killing the agents; the create form posts {slug,name}');
// Loading a workspace starts the category-management poll (a real setInterval),
// which would keep node alive forever once the assertions are done.
process.exit(0);
