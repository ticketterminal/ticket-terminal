// Renders the Settings page's Notion section against a stubbed API in two
// states (disconnected → connected with a database) and checks the form
// offers the right controls in each. No browser: linkedom + a fetch stub.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},location:{protocol:'http:',host:'localhost',hash:'#/settings'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
// linkedom exposes HTMLSelectElement.value as getter-only; real browsers allow
// assignment. Same shim categories.mjs uses, so `sel.value = name` behaves.
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});

let settings={notion:{clientId:'',clientSecretSet:false,clientSecretPreview:'',redirectUri:'http://localhost:4173/api/notion/oauth/callback',connected:false,authMode:'',workspaceName:'',accessTokenPreview:'',databaseId:'',statusProperty:'',priorityProperty:'',lastOauthError:null}};
const calls=[];
// The /api/notion/options payload, as a function so a test can move the sprint
// marker on (inferred → confirmed → no status column) between renders.
let sprintMarker={value:'Current',source:'inferred',inferredFrom:'Sprint 36',options:['Current','Future','Complete'],hasStatusProperty:true};
let sprintRole={name:'Sprint',type:'relation',source:'discovered',target:'Sprints',
  why:['relation to a database of dated rows','92% of sampled tickets link to it','name looks like a sprint']};
const sprints=[{id:'s36',name:'Sprint 36',state:'active',start:'2026-09-07',end:'2026-09-20',url:'',rawStatus:'Current'},
               {id:'s37',name:'Sprint 37',state:'future',start:'2026-09-21',end:'2026-10-04',url:'',rawStatus:'Future'},
               {id:'s38',name:'Sprint 38',state:'future',start:'2026-10-05',end:'2026-10-18',url:'',rawStatus:'Future'},
               {id:'s35',name:'Sprint 35',state:'closed',start:'2026-08-24',end:'2026-09-06',url:'',rawStatus:'Complete'}];
const options=()=>({ok:true,databaseTitle:'Engineering tickets',
    roleOrder:['title','key','status','priority','description','sprint'],
    roleTypes:{title:['title'],key:['unique_id'],status:['status','select'],priority:['select','status'],description:['rich_text','formula'],sprint:['relation']},
    roles:{title:{name:'Name',type:'title',source:'suggested'},
           key:{name:'ID',type:'unique_id',source:'suggested'},
           status:{name:'Status',type:'status',source:'configured'},
           priority:{name:null,type:null,source:'unmapped'},
           description:{name:null,type:null,source:'configured',problem:'the property “Blurb” you mapped to description no longer exists in this database'},
           sprint:{...sprintRole}},
    properties:[{name:'Area',type:'select'},{name:'ID',type:'unique_id'},{name:'Name',type:'title'},{name:'Sprint',type:'relation'},{name:'Status',type:'status'},{name:'Summary',type:'rich_text'}],
    statuses:[{id:'Backlog',name:'Backlog'}],doneStatuses:['Done'],priorities:[],
    sprints,sprintMarker,
    sprintCandidates:[{property:'Sprint',type:'relation',score:6,reasons:['name hint'],target:'Sprints',fillRate:0.92},
                      {property:'Previous Sprints',type:'relation',score:1,reasons:['no linked rows in the sample'],target:'Sprints',fillRate:0}]});
let tokenResult={ok:true};
let syncResult={ok:true,checked:3,added:['ENG-1'],categorized:[]};
globalThis.fetch=async (path,opts)=>{
  calls.push([path,(opts||{}).method||'GET',(opts||{}).body]);
  const json=(body)=>({ok:true,status:200,json:async()=>body});
  if (path==='/api/settings' && (opts||{}).method==='PUT'){ Object.assign(settings.notion, JSON.parse(opts.body).notion); return json({ok:true}); }
  if (path==='/api/settings') return json(settings);
  if (path==='/api/notion/databases') return json({ok:true,databases:[{id:'11111111-2222-3333-4444-555555555555',title:'Engineering tickets'},{id:'aaaaaaaa-0000-0000-0000-000000000000',title:'Other'}]});
  if (path==='/api/notion/options') return json(options());
  if (path==='/api/sync-notion') return json(syncResult);
  if (path==='/api/notion/token') return json(tokenResult);
  throw new Error('unexpected fetch '+path);
};
const tick=()=>new Promise(r=>setTimeout(r,0));
// renderNotionForm fans out several independent fetch chains (databases, options);
// flush enough microtask+timer turns for all of them to settle.
const settle=async()=>{for(let i=0;i<12;i++) await tick();};

const {renderNotionForm}=await import(root+'/public/settings.js');
const form=document.getElementById('settingsNotionForm');

// Disconnected: personal token first, OAuth folded shut, no database picker yet.
await renderNotionForm(); await settle();
assert(form.textContent.includes('Not connected'));
const passwords=[...form.querySelectorAll('input[type=password]')];
assert(passwords[0].placeholder.startsWith('ntn_'),'token input comes first');
assert.equal([...form.querySelectorAll('button')].find(b=>b.textContent==='Connect with token').className,'refreshbtn');
const fold=form.querySelector('details.settingsfold');
assert.equal(fold.open,false,'OAuth fold is shut when no client id is saved');
assert(fold.textContent.includes('Advanced: OAuth'));
const connect=[...form.querySelectorAll('a.refreshbtn')].find(a=>a.textContent==='Connect with Notion');
assert.equal(connect.getAttribute('href'),'/api/notion/oauth/start');
assert.equal(passwords[1].placeholder,'OAuth client secret');
assert.equal([...form.querySelectorAll('button')].find(b=>b.textContent==='Disconnect').hidden,true);
assert.equal([...form.querySelectorAll('button')].find(b=>b.textContent==='Save database & columns'),undefined);

// Saving app credentials PUTs only the notion section and keeps a blank secret out of the way of the server's keep-if-blank rule.
fold.querySelectorAll('input')[0].value='cid-123';
[...form.querySelectorAll('button')].find(b=>b.textContent==='Save OAuth app settings').click();
await settle();
const put=calls.find(c=>c[0]==='/api/settings'&&c[1]==='PUT');
assert.deepEqual(JSON.parse(put[2]),{notion:{clientId:'cid-123',clientSecret:'',redirectUri:'http://localhost:4173/api/notion/oauth/callback'}});

// Connected via OAuth with a database: workspace label, database picker preselects the saved one, column selects populated, Sync now works.
settings.notion={...settings.notion,connected:true,authMode:'oauth',workspaceName:'Acme',accessTokenPreview:'••••abcd',databaseId:'11111111222233334444555555555555',lastOauthError:null};
await renderNotionForm(); await settle();
assert(form.textContent.includes('Connected to workspace “Acme” via OAuth'));
assert.equal(form.querySelector('details.settingsfold').open,true,'OAuth fold opens when OAuth is in use');
assert([...form.querySelectorAll('a.refreshbtn')].some(a=>a.textContent==='Reconnect with Notion'));
assert.equal([...form.querySelectorAll('button')].find(b=>b.textContent==='Disconnect').hidden,false);
const selects=form.querySelectorAll('select');
assert.equal([...selects][0].tagName,'SELECT');
assert.equal([...form.querySelectorAll('select option')].filter(o=>o.textContent==='Engineering tickets')[0].selected,true);

// Role mapping: one select per role, options limited to properties of a fitting type.
const roleMap=form.querySelector('.rolemap');
assert(roleMap,'role mapping table rendered');
const roleRows=[...roleMap.querySelectorAll('.settingsrow select')];
assert.equal(roleRows.length,6,'one select per role');
const statusRole=roleRows[2];
assert.deepEqual([...statusRole.options].map(o=>o.value),['','-','Area','Status'],
  'every status/select property is offered (a plain select is a legitimate status column), plus auto and off — and nothing of another type');
assert(![...statusRole.options].some(o=>o.value==='Summary'),'a rich_text property is never offered as status');
assert.equal(statusRole.value,'Status','an explicit choice is preselected');
assert(roleMap.textContent.includes('you chose “Status”'));
assert(roleMap.textContent.includes('auto-detected “Name”'),'a guess is labelled as a guess, not as a choice');
assert(roleMap.textContent.includes('not mapped'),'an unmapped role says so');
assert(roleMap.textContent.includes('no longer exists in this database'),'a vanished mapped property is reported, not silently re-guessed');
assert(roleMap.textContent.includes('imported with the ticket regardless of mapping'));

// The sprint role carries its own panel: why this relation was picked, which
// status value means "running", and what the server currently makes of it.
const panel=()=>form.querySelector('.sprintmarker');
assert(panel(),'the sprint row has a panel of its own');
assert(roleMap.textContent.includes('discovered “Sprint” (relation)'),'shape-based detection is labelled as such, not as a name guess');
assert(panel().textContent.includes('92% of sampled tickets link to it'),'the discovery reasons are shown, so the pick can be judged');
assert(panel().textContent.includes('“Sprints”'),'…along with which database the relation points at');
assert(panel().textContent.includes('Detected from “Sprint 36”, whose dates cover today'),'an inferred marker says where it came from');
assert(panel().textContent.includes('4 sprints · 1 active · 2 future · 1 closed'),'the sprint list is previewed as counts per state');
const markerSel=panel().querySelector('select');
assert.deepEqual([...markerSel.options].map(o=>o.textContent),['(use dates only)','Current','Future','Complete'],
  'every status option of the sprints database, plus an explicit dates-only choice');
assert.equal(markerSel.value,'Current','the marker in force is preselected');

// Confirming sends exactly the one field — never the whole notion section back —
// and the re-read re-renders the row with the marker now confirmed.
sprintMarker={...sprintMarker,source:'confirmed'};
[...panel().querySelectorAll('button')].find(b=>b.textContent==='Confirm marker').click();
await settle();
assert.deepEqual(JSON.parse(calls.filter(c=>c[0]==='/api/settings'&&c[1]==='PUT').pop()[2]),{notion:{sprintActiveMarker:'Current'}});
assert(panel().textContent.includes('Confirmed'));
assert(!panel().textContent.includes('whose dates cover today'));

// Saving sends the role map, not the old status/priority pair.
[...roleMap.querySelectorAll('.settingsrow select')][4].value='Summary';
[...form.querySelectorAll('button')].find(b=>b.textContent==='Save mapping').click();
await settle();
const mapPut=JSON.parse(calls.filter(c=>c[0]==='/api/settings'&&c[1]==='PUT').pop()[2]);
assert.equal(mapPut.notion.roles.description,'Summary');
assert.equal(mapPut.notion.roles.status,'Status');
assert.equal(mapPut.notion.databaseId,'11111111222233334444555555555555');
assert(!('statusProperty' in mapPut.notion),'the old column fields are gone');

// Switching database clears the stale mapping instead of saving one database's fields against another's id.
await renderNotionForm(); await settle();
const dbSelect=form.querySelector('select');
dbSelect.value='aaaaaaaa-0000-0000-0000-000000000000';
dbSelect.dispatchEvent(new window.Event('change'));
assert.equal(form.querySelector('.rolemap').querySelectorAll('select').length,0,'stale role selects are cleared');
assert(form.querySelector('.rolemap').textContent.includes('Save this database first'));

// Sync reports truncation rather than implying a complete import.
syncResult={ok:true,checked:2000,added:['ENG-1'],categorized:[],truncated:true};
[...form.querySelectorAll('button')].find(b=>b.textContent==='Sync now').click();
await settle();
assert(form.textContent.includes('stopped at the page limit'),'a truncated sync says so');

// A sprints database with no status column at all: say so, and ask nothing —
// there is no value to pick and the dates already answer the question.
sprintMarker={value:'',source:'',inferredFrom:'',options:[],hasStatusProperty:false};
sprintRole={name:'Sprint',type:'relation',source:'configured'};
await renderNotionForm(); await settle();
const datesOnly=form.querySelector('.sprintmarker');
assert(datesOnly.textContent.includes('Dates only — no status column'));
assert.equal(datesOnly.querySelector('select'),null,'nothing to choose from, so no control');
assert.equal([...form.querySelectorAll('button')].find(b=>b.textContent==='Confirm marker'),undefined);
assert(!datesOnly.textContent.includes('92% of sampled tickets'),'reasons belong to a discovered role, not an explicitly chosen one');
assert(datesOnly.textContent.includes('4 sprints · 1 active'),'the preview stands on its own');

// A sprint role that isn't a relation (select/date shapes) gets no panel at all.
sprintRole={name:'Sprint window',type:'date',source:'configured'};
await renderNotionForm(); await settle();
assert.equal(form.querySelector('.sprintmarker'),null,'only a relation-backed sprint role is offered a marker');
sprintRole={name:'Sprint',type:'relation',source:'discovered',target:'Sprints',why:['relation to a database of dated rows']};

// Personal token path: the pasted secret is POSTed, and a rejection is shown inline.
settings.notion={...settings.notion,connected:false,authMode:'',workspaceName:'',databaseId:'',lastOauthError:null};
tokenResult={ok:false,error:'Notion rejected that token (401): API token is invalid.'};
await renderNotionForm(); await settle();
[...form.querySelectorAll('input[type=password]')][0].value='ntn_bad';
[...form.querySelectorAll('button')].find(b=>b.textContent==='Connect with token').click();
await settle();
assert.deepEqual(JSON.parse(calls.filter(c=>c[0]==='/api/notion/token').pop()[2]),{token:'ntn_bad'});
assert(form.textContent.includes('Failed: Notion rejected that token'));

// An OAuth failure stashed by the callback is surfaced.
settings.notion.lastOauthError='invalid_client';
await renderNotionForm(); await settle();
assert(form.textContent.includes('Last connection attempt failed: invalid_client'));
console.log('PASS: Notion settings form — token-first layout, OAuth fold, credential save, role mapping (explicit vs auto vs vanished), database switch clears stale mapping, truncation reporting, token rejection, OAuth error surfacing; sprint discovery reasons, active-sprint marker (inferred/confirmed/dates-only) and sprint preview');
