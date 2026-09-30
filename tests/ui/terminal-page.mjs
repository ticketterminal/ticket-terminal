// The full-page terminal route (opened via "Open in bigger tab" into a real
// separate browser tab) must carry the ticket's own identity in both the
// on-page heading and the actual browser tab title — not the app's generic
// default — and must revert cleanly once the tab leaves this route.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
Object.assign(globalThis,{window,document,localStorage:{getItem:()=>null,setItem:()=>{}},location:{protocol:'http:',host:'localhost',hash:'#/'}});
window.openTicketTerminal=()=>{};

const TICKETS={'OPS-40':{key:'OPS-40',summary:'Rotate the ingress certificate',categories:[]}};
let resolveFetch;
globalThis.fetch=async(url)=>{
  if (String(url).includes('/api/tickets')){
    return new Promise(resolve => { resolveFetch = () => resolve({ok:true,status:200,json:async()=>TICKETS}); });
  }
  return {ok:true,status:200,json:async()=>({})};
};

const DEFAULT_TITLE=document.title;
const {renderTerminalPage,disposeTerminalPage}=await import(root+'/public/terminal-page.js');
const titleEl=document.getElementById('terminalPageTitle');

// --- provisional key+provider headline, then key+summary+provider once data loads ------
{
  const pending=renderTerminalPage('OPS-40','claude');
  assert.equal(titleEl.textContent,'OPS-40 — Claude','shows a provisional headline before the ticket fetch resolves');
  assert.equal(document.title,'OPS-40 — Claude','the browser tab title matches the on-page heading');
  resolveFetch();
  await pending;
  assert.equal(titleEl.textContent,'OPS-40 — Rotate the ingress certificate (Claude)','the heading gains the real ticket summary once it loads');
  assert.equal(document.title,'OPS-40 — Rotate the ingress certificate (Claude)','the tab title gains the real ticket summary too');
}

// --- leaving the route restores the app's own default tab title ------------------------
{
  disposeTerminalPage();
  assert.equal(document.title,DEFAULT_TITLE,'leaving the route restores the default tab title');
}

// --- a fetch that resolves after navigating away must not resurrect the old title -------
{
  renderTerminalPage('OPS-40','claude');
  disposeTerminalPage(); // router.js calls this before rendering the next route, mid-fetch
  resolveFetch();
  await new Promise(r => setTimeout(r, 0));
  assert.equal(document.title,DEFAULT_TITLE,'a stale in-flight fetch must not overwrite the title after navigating away');
}

console.log('terminal-page.mjs OK');
