// The board's sprint scoping: the selector only appears when the tracker has
// sprints, "current" only when one is actually running, and membership is
// tested against every sprint a ticket is in (carry-over). Everything keys off
// the contract's `state` field ("active"/"future"/"closed"), never off a
// tracker's own status wording. No browser: linkedom + a fetch stub.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},location:{protocol:'http:',host:'localhost',hash:'#/'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
window.requestAnimationFrame=callback=>callback();
// linkedom exposes HTMLSelectElement.value as getter-only; real browsers allow
// assignment. Same shim the other suites use, so `sel.value = name` behaves.
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});
globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true})});

const {state}=await import(root+'/public/state.js');
const {passesSprintFilter,renderSprintOptions,activeSprints,normalizeSprintFilter,sprintMembership}=await import(root+'/public/filters.js');
const {renderTicketRow}=await import(root+'/public/ticket-row.js');

const sprint=(name,sprintState,start,end,rawStatus)=>({id:name.toLowerCase().replace(/\s/g,'-'),name,state:sprintState,start:start||'',end:end||'',url:'',rawStatus:rawStatus||''});
const wrap=document.getElementById('sprintWrap');
const sel=document.getElementById('sprintSel');
const note=document.getElementById('sprintNote');
const values=()=>[...sel.options].map(o=>o.value);
const labels=()=>[...sel.options].map(o=>o.textContent);

// A board with no sprint column at all hides the control rather than showing an empty one.
state.sprints=[];
renderSprintOptions();
assert.equal(wrap.hidden,true,'no sprints ⇒ no selector');

// The usual case: one active sprint, and "current" is what the board opens on.
const board=[sprint('Sprint 36','active','2026-09-07','2026-09-20','Current'),
             sprint('Sprint 37','future','2026-09-21','2026-10-04','Future'),
             sprint('Sprint 35','closed','2026-08-24','2026-09-06','Complete'),
             sprint('Backlog sprint','future')];
state.sprints=board;
state.sprintFilter='current';
renderSprintOptions();
assert.equal(wrap.hidden,false);
assert.deepEqual(values(),['current','','none','Sprint 36','Sprint 37','Sprint 35','Backlog sprint'],
  'server order is kept — the board never re-sorts the tracker\'s own sprint list');
assert.equal(labels()[0],'Active sprint — Sprint 36');
assert.equal(labels()[3],'Sprint 36  (2026-09-07) · active');
assert.equal(labels()[6],'Backlog sprint · future','an undated sprint still says what state it is in');
assert.equal(sel.value,'current','the active sprint is preselected by default');
assert.equal(note.textContent,'2026-09-07 → 2026-09-20  ·  Current','the note shows the tracker\'s own wording, not the derived state');
assert.deepEqual(activeSprints().map(s=>s.name),['Sprint 36']);

// Between sprints there is nothing "current" can mean: the option is gone and a
// remembered "current" falls back to all sprints instead of an empty board.
state.sprints=[sprint('Sprint 37','future','2026-09-21','2026-10-04','Future'),sprint('Sprint 35','closed','2026-08-24','2026-09-06','Complete')];
state.sprintFilter='current';
renderSprintOptions();
assert(!values().includes('current'),'no active sprint ⇒ no "current" option');
assert.equal(state.sprintFilter,'','…and the remembered filter falls back to all sprints');
assert.equal(sel.value,'');
assert.equal(note.textContent,'');

// Several sprints running at once (parallel teams) get a count, not one name.
state.sprints=[sprint('Platform 12','active','2026-09-07','2026-09-20','Current'),sprint('Web 12','active','2026-09-07','2026-09-20','Current')];
state.sprintFilter='current';
renderSprintOptions();
assert.equal(labels()[0],'Active sprints (2)');

// A sprint that vanished from the tracker falls back to the active one.
state.sprints=board;
state.sprintFilter='Sprint 21';
renderSprintOptions();
assert.equal(state.sprintFilter,'current');

// ---- passesSprintFilter ----------------------------------------------------
state.sprints=board;
const inSprint=(names,sprintState)=>({sprint:names[0]||'',sprintState:sprintState||'',sprintNames:names,sprintIds:names.map(n=>n.toLowerCase())});

state.sprintFilter='';
assert.equal(passesSprintFilter(inSprint([])),true,'"all sprints" filters nothing out');
state.sprintFilter='current';
assert.equal(passesSprintFilter(inSprint(['Sprint 36'],'active')),true);
assert.equal(passesSprintFilter(inSprint(['Sprint 37'],'future')),false);
assert.equal(passesSprintFilter(inSprint([])),false,'a ticket in no sprint is not in the active one');
// Stale flag: this ticket was synced while Sprint 36 was still upcoming, so it
// carries sprintState "future" — but it IS in the sprint the tracker now calls
// active, so it must show rather than wait for the next sync.
assert.equal(passesSprintFilter(inSprint(['Sprint 35','Sprint 36'],'closed')),true,'stale sprintState falls back to matching an active sprint by name');
assert.equal(passesSprintFilter({sprint:'Sprint 36',sprintState:'active'}),true,'a ticket without sprintNames still passes on its own state');

state.sprintFilter='none';
assert.equal(passesSprintFilter(inSprint([])),true);
assert.equal(passesSprintFilter(inSprint(['Sprint 36'],'active')),false);

state.sprintFilter='Sprint 35';
assert.equal(passesSprintFilter(inSprint(['Sprint 35','Sprint 36'],'active')),true,'a carry-over ticket belongs to both sprints');
assert.equal(passesSprintFilter(inSprint(['Sprint 36'],'active')),false);

// A board with no sprints at all never filters, whatever is remembered.
state.sprints=[];
state.sprintFilter='Sprint 35';
assert.equal(passesSprintFilter(inSprint([])),true);
state.sprints=board;
state.sprintFilter='';

// ---- the row badge ---------------------------------------------------------
state.categories=[];
const row=data=>renderTicketRow({id:data.key,data:()=>data},{});
const activeRow=row({key:'N-1',summary:'Ship it',sprint:'Sprint 36',sprintState:'active',sprintNames:['Sprint 36'],jiraStatus:'In Progress'});
const activeBadge=activeRow.querySelector('.sprintbadge');
assert.equal(activeBadge.textContent,'Sprint 36');
assert(activeBadge.classList.contains('sprintactive'),'the running sprint is highlighted');
assert.equal(activeBadge.title,'Active sprint');

const carried=row({key:'N-2',summary:'Carried over',sprint:'Sprint 35',sprintState:'closed',sprintNames:['Sprint 35','Sprint 36'],jiraStatus:'In Progress'});
const carriedBadge=carried.querySelector('.sprintbadge');
assert(!carriedBadge.classList.contains('sprintactive'),'only sprintState "active" highlights — never the tracker\'s own wording');
assert.equal(carriedBadge.title,'Sprint — also in Sprint 36');

assert.equal(row({key:'N-3',summary:'No sprint',jiraStatus:'Backlog'}).querySelector('.sprintbadge'),null);


// --- review fixes -----------------------------------------------------------
{
  const doc=(data)=>data;
  state.sprints=[sprint('Sprint 36','active','2026-09-15','2026-09-28','Current'),sprint('Sprint 35','closed','2026-09-01','2026-09-07','Last')];
  state.sprintFilter='current';
  // A ticket with NO sprint fields (a Jira ticket, or one synced before sprint support) is not subject to the filter.
  assert.equal(passesSprintFilter(doc({key:'JIRA-1',jiraStatus:'Backlog'})),true,'a mixed board must not silently lose every Jira ticket');
  assert.deepEqual(sprintMembership(doc({})),{subject:false,names:[]});
  // A legacy Notion ticket carrying only the old `sprint` string is normalised, not treated as "no sprint".
  assert.equal(passesSprintFilter(doc({sprint:'Sprint 36'})),true);
  state.sprintFilter='none';
  assert.equal(passesSprintFilter(doc({sprint:'Sprint 36'})),false,'legacy string counts as membership');
  assert.equal(passesSprintFilter(doc({sprintNames:[],sprintState:''})),true);
  // When the tracker's active list is known it is authoritative in BOTH directions on rollover day.
  state.sprintFilter='current';
  assert.equal(passesSprintFilter(doc({sprintNames:['Sprint 35'],sprintState:'active'})),false,'stale "active" from last sprint no longer shows under the new one');
  assert.equal(passesSprintFilter(doc({sprintNames:['Sprint 36'],sprintState:'closed'})),true,'this sprint\'s tickets show even before a sync refreshes their state');
  // Without an active list the stored flag decides.
  state.sprints=[sprint('Sprint 37','future','2026-10-01','2026-10-14','Next')];
  assert.equal(passesSprintFilter(doc({sprintNames:['Sprint 37'],sprintState:'active'})),true);
  // normalizeSprintFilter corrects a remembered value nothing can satisfy, BEFORE filtering, and persists it.
  state.sprints=[sprint('Sprint 36','active','2026-09-15','2026-09-28','Current')];
  state.sprintFilter='Sprint 12';
  normalizeSprintFilter();
  assert.equal(state.sprintFilter,'current');
  assert.equal(storage.get('wmp.sprintFilter'),'current','the correction is remembered, not repeated on every load');
  state.sprints=[sprint('Sprint 37','future','2026-10-01','2026-10-14','Next')];
  state.sprintFilter='current';
  normalizeSprintFilter();
  assert.equal(state.sprintFilter,'','no active sprint: fall back to all, not to an option that does not exist');
  // Several active sprints: the note names them instead of showing one sprint's dates as the scope of all.
  state.sprints=[sprint('Platform 12','active','2026-09-10','2026-09-23','Active'),sprint('Mobile 4','active','2026-09-12','2026-09-25','Active')];
  state.sprintFilter='current';
  renderSprintOptions();
  assert.equal([...sel.options][0].textContent,'Active sprints (2)');
  assert.equal(note.textContent,'Platform 12  ·  Mobile 4');
}

console.log('PASS: sprint selector (hidden with none, "current" only while one is active, server order, fallbacks), passesSprintFilter (all/current/none/specific, sprint-less tickets exempt, legacy string, authoritative active list, normalization persisted), sprint badge highlighting');
