import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}});

const {state}=await import(root+'/public/state.js');
const boardState=await import(root+'/public/board-state.js');

state.defaultWorkspace='alpha';
state.workspaceSlug='';
state.selectedTeams=new Set(['DevOps']);
state.knownTeamNames=new Set(['DevOps','Platform']);
state.selectedStatuses=new Set(['In Progress']);
state.knownStatusNames=new Set(['Backlog','In Progress']);
state.selectedAssignees=new Set(['Ami']);
state.knownAssigneeNames=new Set(['Ami','Dana']);
state.filterPerson='Ami';
state.filterInProgress=true;
state.searchQuery='DEVOPS-796';
state.sprintFilter='Sprint 42';
state.viewMode='workflow';
state.flatSortMode='priority';
state.showNested=false;
state.expandedTickets=new Set(['DEVOPS-796']);
state.terminalPanels={'DEVOPS-796:claude':{visible:true}};
state.agentPanelModes={'DEVOPS-796:claude':'summary'};
boardState.saveBoardState();

state.selectedTeams=null;
state.selectedStatuses=null;
state.selectedAssignees=null;
state.filterPerson='';
state.filterInProgress=false;
state.searchQuery='';
state.viewMode='grouped';
state.expandedTickets=new Set();
state.terminalPanels={};
state.agentPanelModes={};
boardState.loadBoardState();

assert.deepEqual([...state.selectedTeams],['DevOps'],'team filters survive a reload');
assert.deepEqual([...state.selectedStatuses],['In Progress'],'status filters survive a reload');
assert.deepEqual([...state.selectedAssignees],['Ami'],'assignee filters survive a reload');
assert.equal(state.filterPerson,'Ami');
assert.equal(state.filterInProgress,true);
assert.equal(document.getElementById('ticketSearch').value,'DEVOPS-796','search is restored into the actual input');
assert.equal(state.viewMode,'workflow','the workflow view is a persisted selectable board mode');
assert.equal(state.flatSortMode,'priority');
assert.equal(state.showNested,false);
assert(state.expandedTickets.has('DEVOPS-796'));
assert.deepEqual(boardState.getTerminalPanel('DEVOPS-796','claude'),{visible:true});
assert.equal(boardState.getAgentPanelMode('DEVOPS-796','claude'),'summary');

// Restore only the copy in the active view. The same ticket can be rendered
// in grouped, flat and status views at once.
const row=key=>{
  const item=document.createElement('div'); item.className='ticketrow'; item.dataset.ticketKey=key;
  const button=document.createElement('button'); button.className='rowtri'; button.setAttribute('aria-expanded','false');
  button.addEventListener('click',()=>button.setAttribute('aria-expanded','true'));
  item.appendChild(button); return item;
};
const grouped=row('DEVOPS-796');
const flat=row('DEVOPS-796');
document.getElementById('lanes').appendChild(grouped);
document.getElementById('allTicketsList').appendChild(flat);
state.viewMode='flat';
boardState.restoreBoardState();
assert.equal(flat.querySelector('.rowtri').getAttribute('aria-expanded'),'true','the expanded ticket is restored after a board rebuild');
assert.equal(grouped.querySelector('.rowtri').getAttribute('aria-expanded'),'false','hidden duplicate rows are not opened');

// Workspace B starts independently; it must not inherit workspace A's filters.
state.workspaceSlug='beta';
boardState.loadBoardState();
assert.equal(state.selectedTeams,null);
assert.equal(state.filterPerson,'');
assert.equal(state.expandedTickets.size,0);

console.log('board-state.mjs OK');
