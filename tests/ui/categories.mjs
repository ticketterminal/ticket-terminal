import {parseHTML} from 'linkedom';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..', import.meta.url));
const {window,document}=parseHTML(fs.readFileSync(root+'/public/index.html','utf8'));
window.requestAnimationFrame=callback=>callback();
assert.equal(document.querySelector('.banner'),null);
assert(document.querySelector('#ticketsSection .sectionhelptext').textContent.includes('Tracker scan'));
assert(document.querySelector('#settingsview #peopleSection'));
assert.equal(document.querySelector('#gridview #peopleSection'),null);
const storage=new Map();
Object.assign(globalThis,{window,document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},location:{protocol:'http:',host:'localhost',hash:'#/settings'},confirm:()=>true,Event:window.Event});
window.scrollTo=()=>{};
Object.defineProperty(window.HTMLSelectElement.prototype, 'value', {configurable:true,get(){return [...this.options].find(o=>o.selected)?.value || this.options[0]?.value || '';},set(value){for(const option of this.options)option.selected=option.value===value;}});
const {state}=await import(root+'/public/state.js');
const {buildCategoryUI,reorderCategory,setCategoriesExpanded,wireCategoryControls,compareByStatus}=await import(root+'/public/lanes.js');
const {renderCategoryManagement}=await import(root+'/public/category-management.js');
const {renderTicketRow,categoriesForAction,trainFrameForStatus}=await import(root+'/public/ticket-row.js');
const cats=['bugs','features','testing'].map(id=>({id,name:id.toUpperCase(),status:'gap',docs:[],memories:[],skills:[]}));
state.categories=cats;
state.lastTicketDocs=[];state.lastDbRef={};
buildCategoryUI();wireCategoryControls();
const lanes=document.getElementById('lanes');const original=[...lanes.children];
assert([...original[0].querySelectorAll('.lanesort option')].some(n=>n.value==='status'&&n.textContent==='Status'));
assert([...document.querySelectorAll('#flatSortSel option')].some(n=>n.value==='status'));
const statusDocs=[
  ['BACKLOG','Backlog','High','2026-09-12'],
  ['PROGRESS','In Progress','Low','2026-09-11'],
  ['APPROVAL','Awaiting approval','Medium','2026-09-10'],
  ['SELECTED','Selected for Development','Highest','2026-09-09'],
].map(([id,jiraStatus,jiraPriority,createdAt])=>({id,data:()=>({jiraStatus,jiraPriority,createdAt})}));
assert.deepEqual(statusDocs.sort(compareByStatus).map(d=>d.id),['APPROVAL','PROGRESS','SELECTED','BACKLOG']);
const sentinel=document.createElement('div');sentinel.textContent='active terminal';original[0].appendChild(sentinel);
reorderCategory('bugs','testing',true);
assert.deepEqual([...lanes.children].map(n=>n.dataset.categoryId),['features','testing','bugs']);
assert.equal(lanes.lastElementChild,original[0]);assert.equal(sentinel.parentElement,original[0]);
assert.deepEqual(JSON.parse(storage.get('wmp.laneOrder')),['features','testing','bugs']);
setCategoriesExpanded(false);assert([...lanes.children].every(n=>!n.open));
const categoryToggle=document.getElementById('toggleCategoriesBtn');
assert.equal(categoryToggle.textContent,'Expand all');
categoryToggle.click();assert([...lanes.children].every(n=>n.open));
assert.equal(categoryToggle.textContent,'Collapse all');
categoryToggle.click();assert([...lanes.children].every(n=>!n.open));
assert.equal(categoryToggle.textContent,'Expand all');
assert(document.getElementById('manageCategoriesBtn').classList.contains('viewbtn'));
const review={id:'review',at:'2026-09-11T00:00:00Z',ticketCount:2,categories:cats,suggestions:[{suggestionId:'one',status:'pending',action:'rename',id:'bugs',name:'Defects',reason:'Useful wording',affectedTickets:[]}]};
const model={onboarded:true,existingSetup:true,role:'Software engineer',roles:['Software engineer'],presets:{'Software engineer':cats},intervalHours:0,scan:{status:'idle'},reviews:[review],history:[],categories:cats,revision:'base'};
const requests=[];
globalThis.fetch=async(url,options)=>{
 requests.push({url,body:options?.body?JSON.parse(options.body):null});
 let value={ok:true,data:model};
 if(url==='/api/tickets')value={};
 if(url==='/api/people')value={};
 if(url==='/api/team-options')value=[];
 if(url.endsWith('/reviews/review')){model.reviews[0].suggestions[0].status='rejected';}
 return {ok:true,status:200,json:async()=>value};
};
await renderCategoryManagement();
const button=text=>[...document.querySelectorAll('#categoryWorkbench button')].find(n=>n.textContent===text);
assert(button('Apply starter categories'));assert(button('Scan ticket titles now'));
assert(document.getElementById('categoryReviews').textContent.includes('Rename “BUGS” → “Defects”'));
button('Select all').click();
await new Promise(r=>setImmediate(r));
button('Reject selected').click();
await new Promise(r=>setImmediate(r));
assert(requests.some(r=>r.url.endsWith('/reviews/review')&&r.body.decision==='reject'&&r.body.suggestionIds[0]==='one'));
assert(document.getElementById('categoryReviews').textContent.includes('rejected'));

state.jiraStatusOptions=[
  {id:'2',name:'Done'},
  {id:'3',name:'Awaiting approval'},
  {id:'4',name:'Cancelled'},
  {id:'5',name:'Backlog'},
  {id:'6',name:'Selected for Development'},
  {id:'1',name:'In Progress'},
];
const ticket=renderTicketRow({id:'TEST-TRAIN',data:()=>({key:'TEST-TRAIN',summary:'Ship the change',description:'Deploy the certificate rotation to production.\nVerify the ingress afterward.',jiraStatus:'In Progress',categories:['bugs'],contentTags:['kubernetes','certificate rotation']})},{});
document.body.appendChild(ticket);
const expandButton=ticket.querySelector('.rowtri');
const titleText=ticket.querySelector('.tickettitletext');
const linkIcon=ticket.querySelector('.ticketlinkicon');
const expandPanel=ticket.querySelector('.expandpanel');
assert.equal(expandButton.textContent,'▸');
assert.equal(expandButton.getAttribute('aria-expanded'),'false');
assert(expandPanel.hidden);
assert.equal(linkIcon.textContent,'↗');
expandButton.click();
assert.equal(expandButton.textContent,'▾');
assert.equal(expandButton.getAttribute('aria-expanded'),'true');
assert(!expandPanel.hidden);
assert.equal(ticket.querySelector('.ticketdescription').textContent,'Deploy the certificate rotation to production.\nVerify the ingress afterward.');
assert(!ticket.querySelector('.descriptionwrap').open);
expandButton.click();
assert.equal(expandButton.textContent,'▸');
assert(expandPanel.hidden);
// The title text is a second way to trigger the same toggle as the triangle.
titleText.click();
assert(!expandPanel.hidden);
titleText.click();
assert(expandPanel.hidden);
assert.deepEqual([...ticket.querySelectorAll('.contenttag')].map(n=>n.textContent),['kubernetes','certificate rotation']);
assert.equal(ticket.querySelector('.categorymembership').textContent,'Category: BUGS');
assert(![...ticket.querySelectorAll('.contenttag')].some(n=>n.textContent==='BUGS'));
assert.equal(ticket.querySelectorAll('.categoryedit select').length,1);
const categoryEditor=ticket.querySelector('.categoryedit select');
assert.equal(categoryEditor.options[0].textContent,'Edit categories…');
assert.deepEqual([...categoryEditor.querySelectorAll('optgroup')].map(n=>n.label),['Add another category','Remove category','Replace with one category']);
assert([...categoryEditor.options].some(n=>n.value==='add:features'));
assert([...categoryEditor.options].some(n=>n.value==='remove:bugs'));
assert([...categoryEditor.options].some(n=>n.value==='move:testing'));
assert.deepEqual(categoriesForAction(['bugs'],'add:features'),['bugs','features']);
assert.deepEqual(categoriesForAction(['bugs','features'],'remove:bugs'),['features']);
assert.deepEqual(categoriesForAction(['bugs','features'],'move:testing'),['testing']);
assert.deepEqual(['Backlog','Selected for Development','In Progress','Awaiting approval','Done'].map(trainFrameForStatus),[0,1,2,3,4]);
const status=ticket.querySelector('.statussel');
const trainStatus=ticket.querySelector('.trainstatus');
const statusProgress=ticket.querySelector('.statusprogress');
assert.deepEqual([...status.options].map(option=>option.textContent),['Cancelled','Backlog','Selected for Development','In Progress','Awaiting approval','Done']);
assert.equal(trainStatus.dataset.frame,'2');
assert.equal(statusProgress.dataset.frame,'2');
assert.equal(ticket.querySelector('.badgerow').firstElementChild,statusProgress);
assert(status.parentElement.classList.contains('statuslabelsegment'));
assert.equal(status.parentElement.parentElement,statusProgress);
assert.equal(statusProgress.lastElementChild,trainStatus);
assert.equal(ticket.querySelector('.statuslabelsizer').textContent,'In Progress');
status.value='Done';
status.dispatchEvent(new window.Event('change'));
await new Promise(r=>setImmediate(r));
assert.equal(trainStatus.dataset.frame,'4');
assert.equal(statusProgress.dataset.frame,'4');
assert.equal(ticket.querySelector('.statuslabelsizer').textContent,'Done');
assert(ticket.classList.contains('ticket-departing'));
assert(requests.some(r=>r.url.includes('/api/tickets/TEST-TRAIN/jira-transition')&&r.body.statusName==='Done'));
ticket.dispatchEvent(new window.Event('animationend'));
await new Promise(r=>setImmediate(r));
assert(ticket.hidden);

// Uncategorized lane: attached only while a non-done ticket has no category; Notion's Complete group counts as done.
{
  const {renderTickets, UNCATEGORIZED}=await import(root+'/public/lanes.js');
  const {isDone}=await import(root+'/public/filters.js');
  const snap=(id,data)=>({id,data:()=>data});
  state.notionDoneStatuses=['Done','Archived'];
  assert.equal(isDone(snap('N-1',{source:'notion',jiraStatus:'Archived'})),true);
  assert.equal(isDone(snap('J-1',{jiraStatus:'Archived'})),false,'Jira keeps its own fixed done pair');
  renderTickets([snap('N-2',{key:'N-2',source:'notion',summary:'Loose',categories:[],jiraStatus:'Backlog',createdAt:'2026-09-01'}),
                 snap('N-3',{key:'N-3',source:'notion',summary:'Archived loose',categories:[],jiraStatus:'Archived',createdAt:'2026-09-01'}),
                 snap('B-1',{key:'B-1',summary:'Filed',categories:['bugs'],jiraStatus:'Backlog',createdAt:'2026-09-01'})], {});
  const loose=lanes.querySelector('.lane.uncategorized');
  assert(loose && loose===lanes.lastElementChild,'uncategorized lane is attached last');
  assert.equal(loose.dataset.categoryId,UNCATEGORIZED.id);
  assert.equal(loose.querySelector('.lanecount').textContent,'1 ticket','archived one is done, filed one is in its lane');
  assert(!JSON.parse(storage.get('wmp.laneOrder')).includes(UNCATEGORIZED.id),'never persisted into the lane order');
  renderTickets([snap('B-1',{key:'B-1',summary:'Filed',categories:['bugs'],jiraStatus:'Backlog',createdAt:'2026-09-01'})], {});
  assert.equal(lanes.querySelector('.lane.uncategorized'),null,'detached again once empty');
}
console.log('PASS: category controls, content tags and review UI; Done tickets animate out after a successful Jira transition; uncategorized lane + Notion done statuses');
