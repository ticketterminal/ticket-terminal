// The Insights dashboard: a fixed set of tables rendered straight from
// GET /api/insights — no chat, no question box, nothing sent anywhere on load
// beyond that one GET. No browser: linkedom + a fetch stub, like the other suites.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},location:{protocol:'http:',host:'localhost',hash:'#/insights'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
window.requestAnimationFrame=callback=>callback();

const fullPayload={ok:true,data:{
  vendorModel:{
    byVendorModel:[{provider:'claude',model:'Sonnet 5',sessions:2,totalCost:4,avgCost:2,avgCalls:3,avgDurationMs:2000}],
    byCategory:[{provider:'claude',model:'Sonnet 5',category:'bugs',sessions:2,totalCost:4,avgCost:2}],
  },
  caching:{
    byProvider:[{provider:'claude',cacheEfficiency:0.75}],
    wasteCandidates:[{ticketKey:'T-9',provider:'claude',sessionId:'s-9',cacheRatio:0.03,totalTokens:40000,cost:1.2}],
  },
  memory:[{id:'orca-ai-access-guide',readByTickets:5,chars:12000}],
  codeburnOptimize:{summary:{healthGrade:'B',healthScore:80,potentialSavingsCostUSD:12.5,potentialSavingsTokens:50000},
    findings:[{id:'f1',title:'Claude edits more than it reads',explanation:'Read more before editing.',severity:'high',tokensSaved:1000,estimatedSavingsUSD:0.5}]},
  ledgerEntryCount:2,
}};
const emptyPayload={ok:true,data:{
  vendorModel:{byVendorModel:[],byCategory:[]}, caching:{byProvider:[],wasteCandidates:[]},
  memory:[], codeburnOptimize:null, ledgerEntryCount:0,
}};

let responseQueue=[fullPayload];
globalThis.fetch=async(url)=>{
  assert.equal(url,'/api/insights');
  const payload=responseQueue.shift() ?? fullPayload;
  return {ok:true,status:200,json:async()=>payload};
};

const {renderInsightsPage}=await import(root+'/public/insights.js');

await renderInsightsPage();
const body=document.getElementById('insightsBody');

// Vendor/model table: header + one data row.
const vendorRows=[...body.querySelectorAll('.insightstable')][0].querySelectorAll('tr');
assert.equal(vendorRows.length,2,'header + one vendor/model row');
assert(vendorRows[1].textContent.includes('claude'));
assert(vendorRows[1].textContent.includes('Sonnet 5'));
assert(vendorRows[1].textContent.includes('$4.00'),'total cost formatted as currency');

// Caching section: provider efficiency + one waste candidate.
assert(body.textContent.includes('75%'),'cache efficiency shown as a percentage');
assert(body.textContent.includes('T-9'),'waste candidate ticket listed');

// Memory structure table.
assert(body.textContent.includes('orca-ai-access-guide'));
assert(body.textContent.includes('12,000'),'memory file size formatted with thousands separator');

// codeburn optimize findings.
assert(body.textContent.includes('Claude edits more than it reads'));
assert(body.querySelector('.insightsfindinghead .pill.gap'),'high severity renders as the gap pill');

// No "no data yet" empty state when there IS ledger data.
assert(!body.textContent.includes('No session-cost history yet'));

// Refresh re-fetches and re-renders against a fresh (this time empty) response —
// exercises that the button handler is wired, not just the initial load() call.
responseQueue=[emptyPayload];
document.getElementById('insightsRefreshBtn').click();
await new Promise(r=>setTimeout(r,0));
assert(body.textContent.includes('No session-cost history yet'),'empty ledger shows the empty-state note');
// vendor+category+provider+waste+memory = 5 tables, still rendered (just empty) after refresh.
assert.equal(body.querySelectorAll('.insightstable').length,5,'section tables still render (empty) after refresh');

// Re-entering the route (a second renderInsightsPage() call, as router.js does on every
// hashchange) must not stack a second click handler on the static refresh button.
responseQueue=[fullPayload];
await renderInsightsPage();
let fetchCalls=0;
const originalFetch=globalThis.fetch;
globalThis.fetch=async(...args)=>{ fetchCalls++; return originalFetch(...args); };
responseQueue=[fullPayload];
document.getElementById('insightsRefreshBtn').click();
await new Promise(r=>setTimeout(r,0));
assert.equal(fetchCalls,1,'refresh triggers exactly one fetch, not a stacked handler from the earlier render');

console.log('insights.mjs OK');
