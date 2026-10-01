// The memory graph's "+ New memory file" control — the only place a memory file can be
// created at all (server/memory_analysis.py's write_doc refuses to touch a path that doesn't
// already exist). No browser: linkedom + a fetch stub keyed by path/method, vis-network
// stubbed to the surface renderMemoryGraph touches (same pattern as workspaces.mjs).
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
globalThis.vis={DataSet:class{constructor(items){this.items=items||[];}get(){return this.items;}},
  Network:class{constructor(){}on(){}once(){}off(){}fit(){}setData(){}setOptions(){}getSelectedNodes(){return [];}selectNodes(){}focus(){}redraw(){}destroy(){}}};

let nodes=[];
const contents={};
const calls=[];
const body=(url,opts)=>{
  const method=(opts&&opts.method)||'GET';
  if(url==='/api/memory-graph' && method==='GET') return {ok:true,nodes,edges:[]};
  if(url==='/api/memory-graph' && method==='POST'){
    const {id}=JSON.parse(opts.body);
    if(!id) return {ok:false,error:'invalid memory id'};
    if(nodes.some(n=>n.id===id)) return {ok:false,error:'a memory file with that id already exists'};
    nodes.push({id,description:'',type:''});
    contents[id]='---\nname: '+id+'\ndescription: \'\'\n---\n\n';
    return {ok:true,content:contents[id]};
  }
  const docMatch=url.match(/^\/api\/memory-graph\/([^/]+)$/);
  if(docMatch && method==='GET') return {ok:true,content:contents[docMatch[1]]||''};
  if(url.endsWith('/diagram')) return {ok:false,error:'diagram generation failed (claude not authenticated, timed out, or returned nothing usable)'};
  return {ok:true};
};
globalThis.fetch=async(url,opts)=>{calls.push({url,opts}); return {ok:true,status:200,json:async()=>body(url,opts)};};
const settle=async()=>{for(let i=0;i<30;i++) await new Promise(resolve=>setTimeout(resolve,0));};

const {renderMemoryGraph}=await import(root+'/public/memory-graph.js');

// --- the control starts collapsed, reveals an inline id input on click -----
await renderMemoryGraph(); await settle();
const group=document.querySelector('.addmemorygroup');
assert.ok(group,'the add-memory control renders in the controls bar');
const addBtn=group.querySelector('button');
const form=group.querySelector('.addmemoryform');
assert.equal(form.hidden,true,'the inline form starts hidden');
addBtn.click();
assert.equal(form.hidden,false,'clicking reveals the id input + Create button');
assert.equal(addBtn.hidden,true);

// --- blank id: inline error, no network call ---------------------------------------------
const idInput=form.querySelector('.addmemoryinput');
const createBtn=[...form.querySelectorAll('button')].find(b=>b.textContent==='Create');
const msg=form.querySelector('.settingsmsg');
const callsBefore=calls.length;
createBtn.click();
assert.equal(msg.textContent,'Enter an id.');
assert.equal(calls.length,callsBefore,'no fetch fires for a blank id');

// --- a valid id creates the file and opens straight into its edit panel ------------------
idInput.value='getting-started-notes';
createBtn.click();
await settle();
assert.ok(nodes.some(n=>n.id==='getting-started-notes'),'the file was actually created server-side');
assert.equal(document.getElementById('memoryPanel').querySelector('h3')?.textContent,'getting-started-notes',
  'the new file opens directly into the edit panel, through renderMemoryGraph\'s existing focusId path');

// --- a duplicate id surfaces the server's error inline, without tearing down the control --
await renderMemoryGraph(); await settle();
const group2=document.querySelector('.addmemorygroup');
group2.querySelector('button').click();
const form2=group2.querySelector('.addmemoryform');
const idInput2=form2.querySelector('.addmemoryinput');
const createBtn2=[...form2.querySelectorAll('button')].find(b=>b.textContent==='Create');
idInput2.value='getting-started-notes';
createBtn2.click();
await settle();
const msg2=form2.querySelector('.settingsmsg');
assert.equal(msg2.textContent,"Couldn't create: a memory file with that id already exists");
assert.equal(form2.hidden,false,'the form stays open on failure so the id can be edited and retried');

console.log('memory-create.mjs OK');
