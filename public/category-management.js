import {state} from './state.js';
import {apiJson} from './api.js';
import {el} from './dom-utils.js';
import {buildCategoryUI} from './lanes.js';
import {reloadBoard} from './polling.js';
import {routeHash, parseRoute} from './workspaces.js';

let current = null;
let poll = null;
export function categoryRevision(){ return current?.revision; }

async function request(path, body, method='POST'){
  const result = await apiJson('/api/category-management' + path, body === undefined ? undefined : {method, body:JSON.stringify(body)});
  if (!result.ok) throw new Error(result.error || 'Category request failed');
  return result.data;
}
function canApply(){
  if (state.liveTerminalCount > 0) throw new Error('Reload the page to detach open terminals before changing categories. Background sessions will remain available.');
}
function button(label, action, className='refreshbtn'){
  const b = el('button', className, label); b.type='button';
  b.addEventListener('click', async () => {
    b.disabled=true;
    try { await action(); }
    catch(error){ message(error.message, true); }
    finally { b.disabled=false; }
  });
  return b;
}
function message(text, error=false){
  const host=document.getElementById('categoryManagerMessage');
  if (host){ host.textContent=text; host.className='settingsmsg '+(error?'err':'ok'); }
}
function updateNotice(){
  const host=document.getElementById('categoryNotice');
  if (!host || !current) return;
  const count=current.reviews.reduce((n,r)=>n+r.suggestions.filter(s=>s.status==='pending').length,0);
  host.replaceChildren(); host.hidden=current.onboarded && !count && current.scan.status!=='error';
  if (host.hidden) return;
  host.appendChild(el('span',null,!current.onboarded?'Make this board fit your role.':count?`${count} category suggestion${count===1?'':'s'} ready to review.`:'Category scan needs attention.'));
  host.appendChild(button(!current.onboarded?'Choose work role':'Review categories',()=>{ location.hash=routeHash('#/settings'); }));
}
async function applyResult(result){
  current=result;
  state.categories=result.categories;
  buildCategoryUI();
  await reloadBoard();
  window.dispatchEvent(new Event('categories-updated'));
  updateNotice();
  renderCategoryManagement();
}
export async function refreshCategoryManagement(){
  current=await request('');
  updateNotice();
  return current;
}
function previewNames(host, categories){
  host.replaceChildren();
  categories.forEach(cat=>host.appendChild(el('span','categorypreview',cat.name)));
}
function names(ids, categories=current.categories){
  return (ids || []).map(id=>categories.find(c=>c.id===id)?.name || id).join(', ') || 'Uncategorized';
}
function suggestionTitle(s, review){
  const label=names([s.id],review.categories);
  if(s.action==='add') return `Add “${s.name}”`;
  if(s.action==='rename') return `Rename “${label}” → “${s.name}”`;
  if(s.action==='merge') return `Merge “${label}” into “${names([s.targetId],review.categories)}”`;
  return `Move ${s.ticketKeys.length} ticket${s.ticketKeys.length===1?'':'s'} to ${names(s.categoryIds)}`;
}
function renderReviews(){
  const host=document.getElementById('categoryReviews');
  if(!host || !current)return;
  host.replaceChildren();
  const status=document.getElementById('categoryScanStatus');
  status.textContent=current.scan.status==='running'?'Scanning ticket titles… You can leave this page.':current.scan.status==='error'?current.scan.error:current.scan.finishedAt?`Last scan: ${new Date(current.scan.finishedAt).toLocaleString()}`:'No scans yet.';
  const scanButton=document.getElementById('categoryScanNow');
  if(scanButton)scanButton.disabled=current.scan.status==='running';
  if(!current.reviews.length)host.appendChild(el('p','sub','Scan your ticket titles to find useful category changes. Nothing is applied until you accept it.'));
  current.reviews.forEach(review=>{
    const card=el('details','categoryreview');card.open=review.suggestions.some(s=>s.status==='pending');
    card.appendChild(el('summary',null,`${new Date(review.at).toLocaleString()} · ${review.ticketCount} tickets · ${review.suggestions.filter(s=>s.status==='pending').length} pending`));
    const checks=[];
    if(!review.suggestions.length)card.appendChild(el('p','sub','No category changes suggested.'));
    review.suggestions.forEach(s=>{
      const row=el('div','categorysuggestion');
      const label=el('label','suggestionchoice');
      const check=document.createElement('input');check.type='checkbox';check.disabled=s.status!=='pending';check.value=s.suggestionId;
      const title=el('strong',null,suggestionTitle(s,review));label.append(check,title);row.appendChild(label);
      row.appendChild(el('p',null,s.reason));
      if(s.action==='merge')row.appendChild(el('p','sub','All source-category tickets and linked knowledge references move to the destination.'));
      if(s.affectedTickets?.length || s.ticketKeys?.length){
        const details=el('details','affectedtickets');details.appendChild(el('summary',null,`${s.affectedTickets?.length || s.ticketKeys.length} affected tickets`));
        if(s.affectedTickets){
          s.affectedTickets.forEach(ticket=>details.appendChild(el('div',null,`${ticket.key} — ${ticket.title}: ${names(ticket.before,review.categories)} → ${names(ticket.after)}`)));
        }else{
          s.ticketKeys.forEach(key=>details.appendChild(el('div',null,key)));
        }row.appendChild(details);
      }
      if(s.status!=='pending')row.appendChild(el('span','categorydecision',s.status));
      else checks.push(check);
      card.appendChild(row);
    });
    if(checks.length){
      const actions=el('div','settingsactions');
      const decide=async decision=>{
        const ids=checks.filter(c=>c.checked).map(c=>c.value);
        if(!ids.length)throw new Error('Select at least one suggestion.');
        if(decision==='accept')canApply();
        const result=await request('/reviews/'+review.id,{suggestionIds:ids,decision});
        if(decision==='accept')await applyResult(result);
        else{current=result;renderReviews();updateNotice();}
      };
      actions.append(button('Select all',()=>checks.forEach(c=>{c.checked=true;})),button('Accept selected',()=>decide('accept')),button('Reject selected',()=>decide('reject')));
      card.appendChild(actions);
    }
    host.appendChild(card);
  });
}
function renderHistory(){
  const host=document.getElementById('categoryHistory');host.replaceChildren();
  if(!current.history.length)host.appendChild(el('p','sub','Each category change saves the previous version here.'));
  current.history.forEach(version=>{
    const row=el('details','categoryreview');
    row.appendChild(el('summary',null,`${new Date(version.at).toLocaleString()} · ${version.reason}`));
    const preview=el('div','categorypreviews');previewNames(preview,version.categories);row.appendChild(preview);
    row.appendChild(el('p','sub','Restores these categories and their saved ticket assignments. Tickets created later are kept; assignments to removed categories become uncategorized. Notes, sessions, and status stay current.'));
    row.appendChild(button('Restore this version',async()=>{
      canApply();
      if(!confirm('Restore this category version and its ticket assignments? Your current version will be saved so you can undo the restore.'))return;
      await applyResult(await request('/restore/'+version.id,{}));
    }));host.appendChild(row);
  });
}
export async function renderCategoryManagement(){
  const host=document.getElementById('categoryWorkbench');if(!host)return;
  try { await refreshCategoryManagement(); }
  catch(error){host.replaceChildren(el('p','settingsmsg err','Category management unavailable: '+error.message));return;}
  host.replaceChildren();
  host.appendChild(el('h2',null,'Your work, your categories'));
  host.appendChild(el('p','sub','Choose a role for a starter set. Edit the names below, or review AI suggestions based on your ticket titles.'));
  const profile=el('div','categoryprofile');
  const roleLabel=el('label',null,'Work role');const role=document.createElement('input');role.value=current.role;role.placeholder='Choose or enter your role';role.setAttribute('list','categoryRoles');role.maxLength=120;roleLabel.appendChild(role);
  const datalist=document.createElement('datalist');datalist.id='categoryRoles';current.roles.forEach(name=>{const opt=document.createElement('option');opt.value=name;datalist.appendChild(opt);});
  const preview=el('div','categorypreviews');
  const previewRole=()=>previewNames(preview,current.presets[role.value]||current.presets['Software engineer']);
  role.addEventListener('input',previewRole);previewRole();
  const scheduleLabel=el('label',null,'AI review schedule');const schedule=document.createElement('select');
  [[0,'On demand only'],[24,'Daily'],[168,'Weekly']].forEach(([v,name])=>{const opt=document.createElement('option');opt.value=String(v);opt.textContent=name;opt.selected=v===current.intervalHours;schedule.appendChild(opt);});scheduleLabel.appendChild(schedule);
  profile.append(roleLabel,datalist,scheduleLabel);host.appendChild(profile);
  host.appendChild(el('p','sub','Starter categories for this role (custom roles use the general engineering set):'));host.appendChild(preview);
  const actions=el('div','settingsactions');
  actions.append(button('Save role & schedule',async()=>{
    current=await request('/profile',{role:role.value,intervalHours:Number(schedule.value)},'PUT');updateNotice();message('Role and review schedule saved.');
  }),button('Apply starter categories',async()=>{
    canApply();
    if(current.existingSetup && !confirm('Replace current categories with this starter set? Existing assignments that no longer match become uncategorized. Your current categories and assignments will be saved in history.'))return;
    await applyResult(await request('/profile',{role:role.value,intervalHours:Number(schedule.value),applyStarter:true,revision:current.revision},'PUT'));
  }));host.appendChild(actions);
  const msg=el('p','settingsmsg');msg.id='categoryManagerMessage';msg.setAttribute('role','status');host.appendChild(msg);
  host.appendChild(el('h3',null,'AI category review'));
  host.appendChild(el('p','sub','Uses your signed-in Claude CLI to review ticket titles, current category assignments, and your role. No ticket descriptions or notes are sent. Scans use model tokens. Scheduled reviews run while the server is open and wait if suggestions are still pending.'));
  const scan=button('Scan ticket titles now',async()=>{await request('/scan',{});await refreshCategoryManagement();renderReviews();});scan.id='categoryScanNow';host.appendChild(scan);
  const status=el('p','sub');status.id='categoryScanStatus';status.setAttribute('role','status');host.appendChild(status);
  const reviews=el('div');reviews.id='categoryReviews';host.appendChild(reviews);
  host.appendChild(el('h3',null,'Category history'));const history=el('div');history.id='categoryHistory';host.appendChild(history);
  renderReviews();renderHistory();
}
export async function initCategoryManagement(){
  try{
    await refreshCategoryManagement();
    if(!current.onboarded && !current.existingSetup){
      const dialog=document.createElement('dialog');dialog.className='categoryonboarding';
      dialog.appendChild(el('h2',null,'What kind of work do you do?'));
      dialog.appendChild(el('p','sub','Start with categories for your role. You can rename, add, or change them at any time.'));
      const role=document.createElement('select');role.setAttribute('aria-label','Work role');current.roles.forEach(name=>{const opt=document.createElement('option');opt.value=name;opt.textContent=name;role.appendChild(opt);});
      const preview=el('div','categorypreviews');const refresh=()=>previewNames(preview,current.presets[role.value]);role.addEventListener('change',refresh);role.value=current.roles[0];refresh();
      const status=el('p','settingsmsg');
      const start=button('Start with these categories',async()=>{
        try{canApply();await applyResult(await request('/profile',{role:role.value,intervalHours:0,applyStarter:true,revision:current.revision},'PUT'));dialog.close();dialog.remove();}
        catch(error){status.textContent=error.message;}
      });
      dialog.append(role,preview,start,button('Set up later',()=>{dialog.close();dialog.remove();}),status);
      document.body.appendChild(dialog);dialog.showModal();
    }
    if(poll)clearInterval(poll);
    poll=setInterval(async()=>{
      try{await refreshCategoryManagement(); if(parseRoute(location.hash).path==='/settings')renderReviews();}catch(error){}
    },15000);
  }catch(error){/* Older backend: normal board still loads. */}
}
