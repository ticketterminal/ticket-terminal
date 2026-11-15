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
const selectValues=new WeakMap();
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return selectValues.get(this) || [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){selectValues.set(this,value);}});

const fullPayload={ok:true,data:{
  productivity:{ticketsWorked:2,sessions:3,totalCost:4,costPerTicket:2,medianSessionCost:1.25,
    completed:1,awaitingApproval:1,knownStatusTickets:2,changeRequests:3,deliveryTickets:2},
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
  codeburnOptimizeLifetimeOnly:false, ledgerEntryCount:2, totalLedgerEntryCount:8,
  range:{start:null,end:null},
}};
const emptyPayload={ok:true,data:{
  productivity:{ticketsWorked:0,sessions:0,totalCost:0,costPerTicket:null,medianSessionCost:null,
    completed:0,awaitingApproval:0,knownStatusTickets:0,changeRequests:0,deliveryTickets:0},
  vendorModel:{byVendorModel:[],byCategory:[]}, caching:{byProvider:[],wasteCandidates:[]},
  memory:[], codeburnOptimize:null, codeburnOptimizeLifetimeOnly:true,
  ledgerEntryCount:0, totalLedgerEntryCount:8, range:{start:null,end:null},
}};

let responseQueue=[fullPayload];
const requestedUrls=[];
globalThis.fetch=async(url,opts={})=>{
  requestedUrls.push(url);
  assert(url.startsWith('/api/insights'));
  if(url==='/api/insights/refresh'){
    assert.equal(opts.method,'POST');
    return {ok:true,status:200,json:async()=>({ok:true,entries:8,imported:6})};
  }
  const payload=responseQueue.shift() ?? fullPayload;
  return {ok:true,status:200,json:async()=>payload};
};

const {renderInsightsPage}=await import(root+'/public/insights.js');

await renderInsightsPage();
const body=document.getElementById('insightsBody');
assert.equal(document.getElementById('insightsRangePreset').value,'last30','the useful default is a bounded 30-day view');
const initialParams=new URLSearchParams(requestedUrls[0].split('?')[1]);
assert(initialParams.get('start') && initialParams.get('end'),'the default request sends an explicit time window');
assert(document.getElementById('insightsRangeSummary').textContent.includes('2 of 8 sessions'));
assert(body.textContent.includes('Measured productivity'));
assert(body.textContent.includes('3 agent sessions'));
assert(body.textContent.includes('1 done · 1 awaiting approval'));
assert(body.textContent.includes('2 tickets with PR / MR evidence'));
assert(body.textContent.includes('$2.00 / ticket · $1.25 median session'));

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

// All time removes the query bounds and reveals lifetime-only optimization findings.
responseQueue=[fullPayload];
const preset=document.getElementById('insightsRangePreset');
preset.value='all';
preset.dispatchEvent(new window.Event('change'));
await new Promise(r=>setTimeout(r,0));
assert.equal(requestedUrls.at(-1),'/api/insights');

// A custom inclusive range is translated to an exclusive end instant and applied on demand.
preset.value='custom';
preset.dispatchEvent(new window.Event('change'));
document.getElementById('insightsStartDate').value='2026-10-01';
document.getElementById('insightsEndDate').value='2026-10-07';
responseQueue=[emptyPayload];
document.getElementById('insightsApplyRangeBtn').click();
await new Promise(r=>setTimeout(r,0));
const customParams=new URLSearchParams(requestedUrls.at(-1).split('?')[1]);
assert.equal(new Date(customParams.get('start')).getDate(),1);
assert.equal(new Date(customParams.get('end')).getDate(),8,'the through date is inclusive');
assert(!document.getElementById('insightsCustomRange').classList.contains('hidden'));
assert(body.textContent.includes('lifetime-only'),'bounded views do not mix in lifetime savings dollars');
assert.equal(document.getElementById('insightsApplyRangeBtn').textContent,'Apply','apply gives visible progress and restores its label');

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
assert.equal(fetchCalls,2,'refresh performs one explicit ledger sync and one read, without stacked route handlers');

console.log('insights.mjs OK');
