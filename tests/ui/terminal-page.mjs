import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';

const root=fileURLToPath(new URL('../..',import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const calls=[];
Object.assign(globalThis,{
  window,document,
  localStorage:{getItem:()=>null,setItem:()=>{}},
  location:{hash:'#/'},
  fetch:async (url,opts={})=>{
    calls.push({url,opts});
    const body=url.startsWith('/api/tickets') ? {
      'OPS-42':{key:'OPS-42',summary:'Restore the deployment pipeline',categories:[],changeRequests:[]},
    } : {ok:true,changeRequests:[]};
    return {ok:true,status:200,json:async()=>body};
  },
});
window.openTicketTerminal=()=>{};

const {renderTerminalPage,disposeTerminalPage}=await import(root+'/public/terminal-page.js');
await renderTerminalPage('OPS-42','codex');

assert.equal(document.getElementById('terminalPageTitle').textContent,'OPS-42 — Restore the deployment pipeline','the full terminal heading includes the ticket key and headline');
assert.equal(document.getElementById('terminalPageProvider').textContent,'Codex terminal','the provider remains visible without displacing the headline');
assert.equal(document.title,'OPS-42 — Restore the deployment pipeline · Ticket Terminal','the browser tab identifies the ticket and headline');

disposeTerminalPage();
assert.equal(document.title,'Ticket Terminal','leaving the bigger terminal restores the normal app title');

console.log('terminal-page.mjs OK');
