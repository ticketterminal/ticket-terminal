// The "what kind of work do you do?" onboarding dialog (category-management.js's
// initCategoryManagement): a role's preset categories are now editable right there — renamed,
// removed, or added to — before "Start with these categories" applies them. No browser:
// linkedom + a fetch stub that models the real server's apply-preset-then-save-edits sequence
// (PUT /profile, then PUT /api/categories if the preview was actually edited).
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
Object.assign(globalThis,{window,document,location:{protocol:'http:',host:'localhost',hash:'#/'},confirm:()=>true,alert:()=>{},Event:window.Event,
  localStorage:{getItem:()=>null,setItem:()=>{}}});
window.scrollTo=()=>{};
window.requestAnimationFrame=callback=>callback();
// linkedom doesn't implement <dialog> at all — a created one is a plain HTMLElement.
window.HTMLElement.prototype.showModal=function(){ this.open=true; };
window.HTMLElement.prototype.close=function(){ this.open=false; };
// linkedom's HTMLOptionElement.selected doesn't reflect to the attribute its own getter
// reads, so a real browser's `select.value = x` is a no-op here — same shim every other
// test touching a <select> already uses.
Object.defineProperty(window.HTMLOptionElement.prototype,'selected',{configurable:true,
  get(){return this.hasAttribute('selected');},
  set(value){ value ? this.setAttribute('selected','') : this.removeAttribute('selected'); }});
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});

const PRESET=[
  {id:'infrastructure',name:'Infrastructure',status:'gap',color:'#4E79A7',note:'',memories:[],skills:[],docs:[]},
  {id:'ci-and-cd',name:'CI and CD',status:'gap',color:'#59A14F',note:'',memories:[],skills:[],docs:[]},
];
let categories=[];
let onboarded=false;
let revCount=0, revision='r0';
const bump=()=>{revCount++; revision='r'+revCount;};
const statusPayload=()=>({revision,onboarded,existingSetup:false,role:onboarded?'DevOps / SRE':'',intervalHours:0,
  roles:['DevOps / SRE'],presets:{'DevOps / SRE':PRESET.map(c=>({...c}))},
  categories:categories.map(c=>({...c})),history:[],reviews:[],scan:{status:'idle'}});
const calls=[];
globalThis.fetch=async(url,opts)=>{
  calls.push({url,opts});
  const method=(opts&&opts.method)||'GET';
  const json=(body,ok=true,status=200)=>({ok,status,json:async()=>body});
  if(url==='/api/category-management/profile' && method==='PUT'){
    const body=JSON.parse(opts.body);
    if(body.revision!==revision) return json({ok:false,error:'Categories changed. Reload before applying a starter set.'});
    categories=PRESET.map(c=>({...c}));onboarded=true;bump();
    return json({ok:true,data:statusPayload()});
  }
  if(url==='/api/category-management') return json({ok:true,data:statusPayload()});
  if(url.startsWith('/api/categories')){
    if(method==='PUT'){
      const sentRevision=new URL('http://x'+url).searchParams.get('revision');
      if(sentRevision!==revision) return json({ok:false,error:'Categories changed since this editor opened. Reload before saving.'});
      categories=JSON.parse(opts.body);bump();
      return json({ok:true,categories:categories.map(c=>({...c}))});
    }
    return json(categories.map(c=>({...c})));
  }
  if(url==='/api/config') return json({jiraBaseUrl:'',jiraConfigured:false,notionConfigured:false});
  return json({ok:true});
};
const settle=async()=>{for(let i=0;i<30;i++) await new Promise(r=>setTimeout(r,0));};

const {initCategoryManagement}=await import(root+'/public/category-management.js');

// --- the dialog opens with the role's preset shown as editable rows -----------------------
await initCategoryManagement(); await settle();
const dialog=document.querySelector('.categoryonboarding');
assert.ok(dialog,'the onboarding dialog renders for a never-onboarded, never-configured workspace');
let rows=[...dialog.querySelectorAll('.categorypreview.editable')];
assert.equal(rows.length,2,'both preset categories render as editable rows');
assert.equal(rows[0].querySelector('input').value,'Infrastructure');

// --- renaming a row, removing one, and adding a new one all work locally, no network yet --
const callsBeforeEdit=calls.length;
rows[0].querySelector('input').value='Platform';
rows[0].querySelector('input').dispatchEvent(new window.Event('input'));
rows[1].querySelector('.categorypreviewremove').click();
const addBtn=[...dialog.querySelectorAll('button')].find(b=>b.textContent==='+ Add category');
addBtn.click();
rows=[...dialog.querySelectorAll('.categorypreview.editable')];
assert.equal(rows.length,2,'removed CI and CD, added one blank row — still 2 total');
rows[1].querySelector('input').value='On-call';
rows[1].querySelector('input').dispatchEvent(new window.Event('input'));
assert.equal(calls.length,callsBeforeEdit,'every edit so far is local — nothing sent over the wire yet');

// --- "Start with these categories" applies the preset, then saves the edited version ------
const startBtn=[...dialog.querySelectorAll('button')].find(b=>b.textContent==='Start with these categories');
startBtn.click();
await settle();
const profileCall=calls.find(c=>c.url==='/api/category-management/profile');
assert.ok(profileCall,'the starter preset is applied first, exactly like before this feature existed');
const categoriesCall=calls.find(c=>c.url.startsWith('/api/categories') && c.opts?.method==='PUT');
assert.ok(categoriesCall,'the edited list is saved right after, since it differs from the applied preset');
const saved=JSON.parse(categoriesCall.opts.body);
assert.deepEqual(saved.map(c=>c.name),['Platform','On-call']);
assert.ok(saved[1].id,'the new row got a real, slugified id, not a blank one');
assert.notEqual(saved[1].id,saved[0].id);
assert.equal(categories.map(c=>c.name).join(','),'Platform,On-call','the server "db" ends up holding the edited set, not the untouched preset');
assert.equal(document.querySelector('.categoryonboarding'),null,'the dialog closes on success');

console.log('category-onboarding-dialog.mjs OK');
// initCategoryManagement() starts a real setInterval poll (same as workspaces.mjs's note).
process.exit(0);
