// Settings' "Memory source" section: a row-editable list of directories (path + optional
// category), same draft-array/row-builder/single-save pattern as the category editor right
// above it in settings.js. No browser: linkedom + a fetch stub, same shim categories.mjs/
// notion-settings.mjs use for a <select>'s value (linkedom doesn't reflect it natively).
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
Object.assign(globalThis,{window,document,localStorage:{getItem:()=>null,setItem:()=>{}},
  location:{protocol:'http:',host:'localhost',hash:'#/settings'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
Object.defineProperty(window.HTMLOptionElement.prototype,'selected',{configurable:true,
  get(){return this.hasAttribute('selected');},
  set(value){ value ? this.setAttribute('selected','') : this.removeAttribute('selected'); }});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});

// Mirrors memory_dirs_info's own precedence (server/memory_analysis.py): whatever was
// explicitly saved wins, each entry tagged source "settings"; with nothing saved, fall back
// to one derived-default entry — same shape GET /api/settings actually returns.
const DEFAULT_DIR={path:'/home/.claude/projects/-x/memory',categoryId:'',source:'default'};
let configuredDirs=[];
let graphNodes=[];
const calls=[];
globalThis.fetch=async(url,opts)=>{
  calls.push({url,opts});
  const json=(body)=>({ok:true,status:200,json:async()=>body});
  if(url==='/api/settings' && opts?.method==='PUT'){ configuredDirs=JSON.parse(opts.body).memoryDirs; return json({ok:true}); }
  if(url==='/api/settings'){
    const effective=configuredDirs.length ? configuredDirs.map(d=>({...d,source:'settings'})) : [DEFAULT_DIR];
    return json({memoryDirs:effective});
  }
  if(url==='/api/memory-graph') return json({ok:true,nodes:graphNodes,edges:[]});
  throw new Error('unexpected fetch '+url);
};

const {state}=await import(root+'/public/state.js');
const {renderMemoryForm}=await import(root+'/public/settings.js');
state.categories=[{id:'infra',name:'Infrastructure',status:'gap',color:'#4E79A7',note:'',docs:[],memories:[],skills:[]}];
const form=document.getElementById('settingsMemoryForm');

// --- nothing explicitly configured: empty editable list, the resolved default shown read-only
await renderMemoryForm();
assert.ok(form.textContent.includes('No directories configured yet'));
assert.equal(form.querySelectorAll('.categoryeditrow').length,0,'the default fallback isn\'t pre-filled into the editable list');
assert.ok(form.textContent.includes('/home/.claude/projects/-x/memory'),'but it does show as the "currently reading from" hint');

// --- add a row, assign it to a category, save ----------------------------------------------
const addBtn=[...form.querySelectorAll('button')].find(b=>b.textContent==='+ Add directory');
addBtn.click();
let row=form.querySelector('.categoryeditrow');
assert.ok(row,'adding a directory shows one editable row');
const pathInput=row.querySelector('input');
pathInput.value='/Users/ami/devops-memory';
pathInput.dispatchEvent(new window.Event('input'));
const catSel=row.querySelector('select');
assert.equal([...catSel.options].map(o=>o.textContent)[0],'— Unassigned —','the category select always offers Unassigned first');
catSel.value='infra';
catSel.dispatchEvent(new window.Event('change'));

const saveBtn=[...form.querySelectorAll('button')].find(b=>b.textContent==='Save memory sources');
saveBtn.click();
await new Promise(r=>setTimeout(r,0));
await new Promise(r=>setTimeout(r,0));
const saveCall=calls.find(c=>c.url==='/api/settings' && c.opts?.method==='PUT');
assert.ok(saveCall,'saving PUTs /api/settings');
assert.deepEqual(JSON.parse(saveCall.opts.body).memoryDirs,[{path:'/Users/ami/devops-memory',categoryId:'infra'}],
  'the whole list is sent in one PUT, same whole-list-replace convention as categories');

// --- after saving, the form re-renders from the server's response: one real row now --------
assert.equal(document.querySelectorAll('#settingsMemoryForm .categoryeditrow').length,1);

// --- Remove deletes the row locally without a save round-trip ------------------------------
row=document.querySelector('#settingsMemoryForm .categoryeditrow');
const removeBtn=[...row.querySelectorAll('button')].find(b=>b.textContent==='Remove');
const callsBeforeRemove=calls.length;
removeBtn.click();
assert.equal(document.querySelectorAll('#settingsMemoryForm .categoryeditrow').length,0);
assert.equal(calls.length,callsBeforeRemove,'Remove is a local draft edit — nothing is sent until Save is clicked');

console.log('memory-settings-form.mjs OK');
