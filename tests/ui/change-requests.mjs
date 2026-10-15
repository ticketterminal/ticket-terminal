import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const calls=[];
Object.assign(globalThis,{
  window,document,URL,
  localStorage:{getItem:()=>null,setItem:()=>{}},
  location:{hash:'#/'},
  fetch:async (url,opts={})=>{
    calls.push({url,opts});
    if(url.includes('/change-requests/refresh')) return {ok:true,status:200,json:async()=>({ok:true,changeRequests:[
      {url:'https://gitlab.com/acme/platform/-/merge_requests/42',provider:'gitlab',repository:'acme/platform',number:42,source:'claude-pr-link'}
    ]})};
    return {ok:true,status:200,json:async()=>({})};
  },
});

const {createChangeRequestView,mergeChangeRequests}=await import(root+'/public/change-requests.js');
assert.equal(mergeChangeRequests(
  [{url:'https://github.com/acme/app/pull/4#discussion'}],
  [{url:'https://github.com/acme/app/pull/4'}],
).length,1,'canonical URLs are deduplicated');

const data={key:'T-1',changeRequests:[]};
const view=createChangeRequestView('T-1',data);
document.body.appendChild(view.shell);
await view.refresh();
assert.equal(view.shell.querySelector('.changerequest-chip a').textContent,'platform !42 ↗');
assert.equal(calls[0].url,'/api/tickets/T-1/change-requests/refresh');

const form=view.shell.querySelector('.changerequest-form');
form.querySelector('input').value='https://github.com/acme/app/pull/7';
form.dispatchEvent(new window.Event('submit'));
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(view.shell.querySelectorAll('.changerequest-chip').length,2,'manual links join discovered links without replacing them');
assert(calls.some(call=>call.opts.method==='PATCH'),'manual links are persisted explicitly');
view.dispose();

console.log('change-requests.mjs OK');
