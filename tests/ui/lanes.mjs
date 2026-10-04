// Parent/child ticket grouping (buildLaneItems), the "show nested"/"show flat" toggle, search
// pulling in a matched subtask's parent for context, and a ticket row's "Linked tickets"
// section (label + in-app search jump + Jira link). No browser: linkedom + a fetch stub.
import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},location:{protocol:'http:',host:'localhost',hash:'#/'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
window.requestAnimationFrame=callback=>callback();
window.HTMLElement.prototype.scrollIntoView=()=>{};
Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,
  get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},
  set(value){for(const option of this.options) option.selected = option.value===value;}});
globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true})});

const {state}=await import(root+'/public/state.js');
const {buildLaneItems,renderLaneItems,renderStatusBoard,resetStatusBoardColumns}=await import(root+'/public/lanes.js');
const {renderSearch,searchForTicket}=await import(root+'/public/filters.js');
const {renderTicketRow}=await import(root+'/public/ticket-row.js');

const doc=(key,fields)=>({id:key,data:()=>({key,summary:'Summary of '+key,...fields})});
const cmp=(a,b)=>a.id.localeCompare(b.id);

// --- buildLaneItems: nested vs flat ------------------------------------------------------
{
  const parent=doc('OPS-1',{});
  const child=doc('OPS-2',{parentKey:'OPS-1'});
  const stray=doc('OPS-3',{});

  state.showNested=true;
  const nested=buildLaneItems([parent,child,stray],cmp);
  assert.equal(nested.length,2,'the child is grouped under its parent, not a third top-level item');
  const parentItem=nested.find(i=>i.doc.id==='OPS-1');
  assert.equal(parentItem.type,'parent');
  assert.deepEqual(parentItem.children.map(c=>c.id),['OPS-2']);
  assert.equal(nested.find(i=>i.doc.id==='OPS-3').type,'ticket');

  state.showNested=false;
  const flat=buildLaneItems([parent,child,stray],cmp);
  assert.equal(flat.length,3,'"show flat" ignores parentKey entirely, same as before nesting existed');
  assert.ok(flat.every(i=>i.type==='ticket'));
  state.showNested=true;
}

// --- renderLaneItems: an epic's own row renders flush, only children collapse -----------
{
  const parent=doc('OPS-30',{issueType:'Epic',summary:'Ship the migration'});
  const child=doc('OPS-31',{parentKey:'OPS-30',summary:'Cut the base image'});
  const container=document.createElement('div');
  renderLaneItems(container, [{type:'ticket',doc:doc('OPS-29',{})}, {type:'parent',doc:parent,children:[child]}], {}, cmp);
  const topLevelRows=[...container.children].filter(c=>c.classList.contains('ticketrow'));
  assert.equal(topLevelRows.length,2,'the plain ticket and the epic parent both render as flush top-level rows, not boxed');
  assert.ok(!container.querySelector('.epicbox'),'the epic parent is no longer wrapped in its own box');
  const wrap=container.querySelector('.epicchildrenwrap');
  assert.ok(wrap,'children render inside a collapsible wrap');
  assert.equal(wrap.open,true,'children are expanded by default');
  assert.equal(wrap.querySelector('summary').textContent,'1 sub-task');
  assert.ok(wrap.querySelector('.epicchildren .ticketrow'),'the child ticket renders inside the wrap');
}

// --- search pulls in a matched subtask's parent, for context ----------------------------
{
  const parent=doc('OPS-10',{summary:'Migrate the ingest pipeline'});
  const child=doc('OPS-11',{parentKey:'OPS-10',summary:'Rotate the staging credential'});
  const unrelated=doc('OPS-12',{summary:'Unrelated housekeeping'});
  state.lastTicketDocs=[parent,child,unrelated];
  state.lastDbRef={};
  state.showNested=true;

  const searchInput=document.getElementById('ticketSearch');
  const searchList=document.getElementById('searchList');
  searchInput.value='staging credential'; // matches only the child's summary
  renderSearch();
  assert.ok(searchList.textContent.includes('OPS-11'),'the actual match renders');
  assert.ok(searchList.textContent.includes('OPS-10'),'its parent is pulled in for context even though it did not match the query itself');
  assert.equal(document.getElementById('searchCount').textContent,'1 ticket','the count reflects real matches only, not the context row');

  state.showNested=false;
  searchInput.value='staging credential';
  renderSearch();
  assert.ok(!searchList.textContent.includes('OPS-10'),'"show flat" also turns off the parent-context pull-in for search');
  searchInput.value='';
  state.showNested=true;
}

// --- searchForTicket: the "open in Ticket Terminal" half of a linked-ticket row ----------
{
  const searchInput=document.getElementById('ticketSearch');
  searchForTicket('OPS-99');
  assert.equal(searchInput.value,'OPS-99');
  searchInput.value='';
}

// --- Jira-style status board ------------------------------------------------------------
{
  state.jiraStatusOptions=[{id:'4',name:'Cancelled'},{id:'1',name:'Backlog'},{id:'2',name:'In Progress'},{id:'3',name:'Done'}];
  state.notionStatusOptions=[];
  state.selectedStatuses=new Set(['Backlog','In Progress','Done','Cancelled']);
  state.selectedTeams=null;
  state.selectedAssignees=null;
  state.filterPerson='';
  state.filterInProgress=false;
  state.lastTicketDocs=[
    doc('OPS-40',{jiraStatus:'Backlog',jiraPriority:'Low'}),
    doc('OPS-41',{jiraStatus:'In Progress',jiraPriority:'High'}),
    doc('OPS-42',{jiraStatus:'Done',jiraPriority:'Medium'}),
    doc('OPS-43',{jiraStatus:'Cancelled',jiraPriority:'Medium'}),
  ];
  state.lastDbRef={};
  renderStatusBoard();
  const board=document.getElementById('statusBoardView');
  assert.deepEqual([...board.querySelectorAll('.statuscolumnhead h3')].map(n=>n.textContent),['Backlog','In Progress','Done','Cancelled'],'standard Jira statuses follow workflow order, not the raw API order');
  assert.equal(board.querySelector('[data-status="Done"] .tickettitletext').textContent,'OPS-42 — Summary of OPS-42','completed tickets remain visible in the Done column');
  const backlogColumn=board.querySelector('[data-status="Backlog"]');
  const backlogExpand=backlogColumn.querySelector('.rowtri');
  backlogExpand.click();
  assert(backlogColumn.classList.contains('statuscolumn-expanded'),'expanding a ticket doubles its status column');
  backlogExpand.click();
  assert(!backlogColumn.classList.contains('statuscolumn-expanded'),'collapsing the ticket restores the column');
  backlogColumn.classList.add('statuscolumn-expanded');
  resetStatusBoardColumns();
  assert(!backlogColumn.classList.contains('statuscolumn-expanded'),'the status-board control can restore every column at once');
  assert(board.classList.contains('statusboard-reset-columns'),'the reset also overrides tickets that remain expanded');
  backlogExpand.click();
  assert(!board.classList.contains('statusboard-reset-columns'),'the next ticket toggle restores automatic column sizing');
  state.selectedStatuses.delete('Backlog');
  renderStatusBoard();
  assert.equal(board.querySelector('[data-status="Backlog"]'),null,'the status filter hides its whole board column');
}

// --- a ticket row's "Linked tickets" section --------------------------------------------
{
  state.jiraBaseUrl='https://orca-ai.atlassian.net';
  const ticket=renderTicketRow({id:'OPS-20',data:()=>({
    key:'OPS-20',summary:'Ship the release',
    linkedIssues:[
      {key:'OPS-5',label:'is blocked by',summary:'Cut the base image'},
      {key:'OPS-6',label:'relates to',summary:''},
    ],
  })},{});
  document.body.appendChild(ticket);
  const lines=[...ticket.querySelectorAll('.linkedissueline')];
  assert.equal(lines.length,2);
  assert.equal(lines[0].querySelector('.linkedissuelabel').textContent,'is blocked by:');
  assert.equal(lines[0].querySelector('.linkedissuekey').textContent,'OPS-5 — Cut the base image');
  assert.equal(lines[1].querySelector('.linkedissuekey').textContent,'OPS-6'); // no summary: key alone, no trailing " — "
  const jiraLink=lines[0].querySelector('.linkedissuejira');
  assert.equal(jiraLink.getAttribute('href'),'https://orca-ai.atlassian.net/browse/OPS-5');
  assert.equal(jiraLink.getAttribute('target'),'_blank');

  const searchInput=document.getElementById('ticketSearch');
  lines[0].querySelector('.linkedissuekey').click();
  assert.equal(searchInput.value,'OPS-5','clicking a linked ticket key jumps the search box to it');
  ticket.remove();
}

console.log('lanes.mjs OK');
