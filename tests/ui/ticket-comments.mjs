import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const calls=[];
let comments=[{id:'1',body:'Initial note',author:'Dana',createdAt:'2026-10-01T10:00:00Z',updatedAt:'',editable:true}];
Object.assign(globalThis,{
  window,document,URL,
  localStorage:{getItem:()=>null,setItem:()=>{}},
  location:{hash:'#/'},
  fetch:async (url,opts={})=>{
    calls.push({url,opts});
    if(opts.method==='POST') return {ok:true,status:200,json:async()=>({ok:true,comment:{id:'2',body:'New note',author:'Bot',editable:true}})};
    if(opts.method==='PATCH') return {ok:true,status:200,json:async()=>({ok:true,comment:{...comments[0],body:'Edited note'}})};
    return {ok:true,status:200,json:async()=>({ok:true,tracker:'jira',comments})};
  },
});

const {createTicketCommentsView}=await import(root+'/public/ticket-comments.js');
const view=createTicketCommentsView('ENG-1',{key:'ENG-1'});
document.body.appendChild(view.shell);
view.start();
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.shell.querySelector('.trackercomment-body').textContent,'Initial note');

view.shell.querySelector('.trackercomment-edit').dispatchEvent(new window.Event('click'));
const editor=view.shell.querySelector('.trackercomment-editor');
editor.querySelector('textarea').value='Edited note';
editor.dispatchEvent(new window.Event('submit'));
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.shell.querySelector('.trackercomment-body').textContent,'Edited note');
assert(calls.some(call=>call.opts.method==='PATCH'));

const add=view.shell.querySelector('.trackercomment-add');
add.querySelector('textarea').value='New note';
add.dispatchEvent(new window.Event('submit'));
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.shell.querySelectorAll('.trackercomment').length,2);
assert(calls.some(call=>call.opts.method==='POST'));
view.stop();

const demo=createTicketCommentsView('DEMO-1',{key:'DEMO-1',isDemo:true});
assert.equal(demo.shell.querySelector('.trackercomment-add textarea').disabled,true);
assert.equal(demo.shell.querySelector('.trackercomments-refresh').disabled,true);

console.log('ticket-comments.mjs OK');
