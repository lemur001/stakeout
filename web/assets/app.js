import {api,setCsrf} from './api.js';
import {showSetup} from './setup.js';
import * as P from './pages.js';
import * as D from './dialogs.js';
import * as H from './discovery.js';
import {escape as e,icon,dialog,closeDialogs,toast,button} from './ui.js';
let state,user,session,pendingMfa=null,settingUp=false,route='overview',outreachTab='all';
const filters={city:'',query:'',status:'',website:''};const selected=new Set();
const root=document.querySelector('#app');
function currentRoute(){const r=location.hash.slice(1).split('?')[0];return P.navItems.some(x=>x[0]===r)?r:'overview';}
function renderPage(){if(!state)return;const el=document.querySelector('#page');if(!el)return;
 if(route==='discovery')H.render(state,el);
 else el.innerHTML=route==='prospects'?P.prospects(state,filters,selected):route==='outreach'?P.outreach(state,outreachTab):P[route](state,user);
 document.title=`${P.navItems.find(x=>x[0]===route)[2]} · Stakeout Civic`;
}
function render(){if(!state||settingUp)return;route=currentRoute();root.innerHTML=P.shell(state,route,user);renderPage();}
function go(to){closeDialogs();document.body.classList.remove('nav-open');if(location.hash==='#'+to){route=to;render();}else location.hash=to;}
async function reload(full=true){state=await api('/api/state');if(full)render();}
function loginScreen(error='') {root.innerHTML=`<main class="login-layout"><div class="login-brand"><img src="/assets/favicon.svg" alt="" width="44" height="44"><strong>Stakeout Civic</strong></div><section class="login-card"><h1>Your community workspace.</h1><p>Sign in to manage research, sponsorships and website delivery.</p>${error?`<p class="login-error" role="alert">${e(error)}</p>`:''}<form data-form="login"><label class="field"><span>Email address</span><input type="email" name="email" required autocomplete="username"></label><label class="field"><span>Password</span><input type="password" name="password" required maxlength="512" autocomplete="current-password"></label><label class="field"><span>Authenticator or recovery code</span><input name="code" autocomplete="one-time-code" maxlength="64"><small>Required when two-factor authentication is enabled.</small></label><button type="submit" class="btn primary">Sign in ${icon('arrow')}</button></form><p class="muted login-help">Access is restricted to your agency’s approved operators.</p></section></main>`;}
async function setupWizard(newAdmin=false){settingUp=true;closeDialogs();await showSetup(root,{newAdmin,onSession:r=>{user=r.user;setCsrf(r.csrf);},onDone:async()=>{settingUp=false;location.hash='overview';await reload();}});}
async function afterLogin(){if(user?.role==='admin'){const c=await api('/api/setup/checklist');if(c.production&&!c.complete)return setupWizard();}await reload();}
async function init(){try{const s=await api('/api/setup/status');if(s.needs_setup)return setupWizard(true);session=await api('/api/session');user=session.user;setCsrf(session.csrf);if(!user)return loginScreen();await afterLogin();}catch(error){root.innerHTML=`<main class="public-card"><h1>The workspace did not load.</h1><p>${e(error.message)}</p><button class="btn primary" data-action="reload-page">Try again</button></main>`;}}
async function openMessage(id){D.messageSheet(state,await api('/api/messages/'+id));}
function formValues(form){return Object.fromEntries(new FormData(form));}
async function saveMessage(form){const v=formValues(form);return api('/api/messages/'+form.dataset.id,{subject:v.subject,body:v.body},'PATCH');}
function fail(error){if(error.status===401){user=null;closeDialogs();loginScreen('Your session expired. Sign in again.');}else toast(error.message,true);}
async function clickAction(target){const a=target.dataset.action,id=target.dataset.id;
 if(a.startsWith('hunt-'))return H.action(state,a,id,reload);
 if(a.startsWith('go-')){go(a.slice(3));return;}
 switch(a){
 case 'setup-wizard':return setupWizard();
 case 'account-mfa':return dialog('modal','Authenticator & recovery codes','Enroll an authenticator or replace an existing one. Replacement revokes old recovery codes and signs out other sessions.',`<form data-form="mfa-enroll" class="form-body"><label class="field"><span>Current password</span><input type="password" name="password" required autocomplete="current-password"></label><label class="field"><span>Current authenticator or recovery code</span><input name="code" autocomplete="one-time-code" maxlength="64"><small>Leave blank only if you have not enrolled MFA yet.</small></label><button class="btn primary" type="submit">Set up authenticator</button></form>`);
 case 'account-password':return dialog('modal','Change password','Your current password and a fresh authenticator or recovery code are required.',`<form data-form="password" class="form-body"><label class="field"><span>Current password</span><input type="password" name="password" required autocomplete="current-password"></label><label class="field"><span>Authenticator or recovery code</span><input name="code" autocomplete="one-time-code" maxlength="64"></label><label class="field"><span>New password</span><input type="password" name="new_password" required minlength="16" maxlength="512" autocomplete="new-password"></label><button class="btn primary" type="submit">Change password and revoke other sessions</button></form>`);
 case 'reload-page':return location.reload();
 case 'menu':document.body.classList.toggle('nav-open');return;
 case 'close-sheet':document.querySelector('#sheet').close();return;
 case 'close-modal':document.querySelector('#modal').close();return;
 case 'close-dialogs':closeDialogs();return;
 case 'refresh':await reload();toast('Workspace refreshed.');return;
 case 'logout':await api('/api/logout',{});user=null;setCsrf('');closeDialogs();loginScreen();return;
 case 'new-city':return D.cityForm();
 case 'new-client':return D.clientForm(state);
 case 'edit-client':return D.clientForm(state,id);
 case 'review':return D.reviewSheet(state,id);
 case 'add-evidence':document.querySelector('#evidence-rows').insertAdjacentHTML('beforeend',D.evidenceRow());return;
 case 'remove-evidence':target.closest('.evidence-row').remove();return;
 case 'add-contact':return D.contactForm(state,id);
 case 'filter-status':filters.status=target.dataset.value;selected.clear();renderPage();return;
 case 'clear-selection':selected.clear();renderPage();return;
 case 'open-city':filters.city=id;filters.query=filters.status=filters.website='';return go('prospects');
 case 'new-research':if(!state.cities.length)return D.cityForm();return D.researchForm(state,id);
 case 'import-report':return D.reportForm(state);
 case 'new-source':return D.sourceForm(state);
 case 'reserve-one':return D.reserveForm(state,[id]);
 case 'reserve-selected':return D.reserveForm(state,[...selected]);
 case 'exclude':case 'suppress':return D.reasonForm(a,id);
 case 'inspect-research':return D.researchSheet(state,id);
 case 'retry-research':return D.retryForm(id,state.research.find(x=>x.id===id)?.state);
 case 'candidate-json':return D.candidateForm(id);
 case 'source-traces':{const traces=await api('/api/research/'+id+'/traces');return dialog('modal','Source-call audit','Only the run’s permitted read-only research calls are shown.',`<div class="form-body"><pre class="report-text">${e(traces.length?JSON.stringify(traces,null,2):'No source calls recorded.')}</pre></div>`,true);}
 case 'outreach-tab':outreachTab=target.dataset.value;renderPage();return;
 case 'draft':{const m=await api('/api/conversations/'+id+'/draft',{});await reload();toast('Draft created. Nothing has been sent.');return openMessage(m.id);}
 case 'message':return openMessage(id);
 case 'approve-message':{const f=target.closest('dialog').querySelector('form');if(!f.reportValidity())return;await saveMessage(f);await api('/api/messages/'+id+'/approve',{});await reload();await openMessage(id);toast('Exact message approved. It has not been queued or sent.');return;}
 case 'queue-message':if(!confirm('Queue this exact approved message for live delivery? The worker will recheck evidence, suppression and sender setup.'))return;await api('/api/messages/'+id+'/queue',{});await reload();await openMessage(id);toast('Approved email queued.');return;
 case 'toggle-pause':if(state.settings.paused&&!confirm('Resume the dispatch worker? Only queued messages that pass all live sending checks can be sent.'))return;await api('/api/settings/pause',{paused:!state.settings.paused});await reload();toast(state.settings.paused?'Outreach paused.':'Workspace pause removed. Other sending gates still apply.');return;
 case 'record-reply':return D.eventForm(state,id);
 case 'new-project':return D.agreementForm(state,id);
 case 'project':return D.projectSheet(state,id);
 case 'directory':return D.directoryForm(id);
 case 'reconcile':return D.reconcileForm(id);
 case 'close-conversation':if(!confirm('Close this conversation and cancel pending messages? Contact history remains locked to prevent a new pitch.'))return;await api('/api/conversations/'+id+'/close',{});await reload();toast('Conversation closed.');return;
 default:throw new Error('This action is not available. Refresh the workspace.');
 }
}
document.addEventListener('click',async ev=>{const t=ev.target.closest('[data-action]');if(!t||t.disabled)return;ev.preventDefault();t.disabled=true;try{await clickAction(t);}catch(error){fail(error);}finally{t.disabled=false;}});
document.addEventListener('submit',async ev=>{
 const form=ev.target;if(!form.matches('[data-form]'))return;ev.preventDefault();if(!form.reportValidity())return;
 const kind=form.dataset.form,id=form.dataset.id,v=formValues(form);const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
 try{
  if(kind==='login'){const result=await api('/api/login',{email:v.email,password:v.password,code:v.code});user=result.user;setCsrf(result.csrf);await afterLogin();return;}
  if(kind==='password'){const result=await api('/api/security/password',v);user=result.user;setCsrf(result.csrf);closeDialogs();toast('Password changed. Other sessions were signed out.');return;}
  if(kind==='mfa-enroll'){
   const result=await api('/api/security/mfa/enrollment',v);pendingMfa={password:v.password,enrollment:result.enrollment};
   dialog('modal','Add your authenticator','Enter the setup key into a time-based authenticator account.',`<form data-form="mfa-confirm" class="form-body"><label class="field"><span>New authenticator setup key</span><input readonly value="${e(result.secret)}"></label><label class="field"><span>New authenticator code</span><input name="new_code" required pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code"></label><label class="field"><span>Current authenticator or recovery code</span><input name="code" maxlength="64" autocomplete="off"><small>If replacing MFA, use a fresh code from your old authenticator or another unused recovery code. Otherwise leave blank.</small></label><button class="btn primary" type="submit">Confirm authenticator</button></form>`);return;
  }
  if(kind==='mfa-confirm'){
   if(!pendingMfa)throw new Error('Start authenticator setup again.');
   const result=await api('/api/security/mfa/confirm',{...pendingMfa,...v});pendingMfa=null;user=result.user;setCsrf(result.csrf);
   dialog('modal','Save your new recovery codes','These replace your old codes. Each works once. Save them privately in a password manager.',`<form data-form="mfa-saved" class="form-body"><pre class="recovery-codes">${result.recovery_codes.map(e).join('\n')}</pre><label class="checkbox-line"><input name="saved" type="checkbox" required><span>I saved these recovery codes securely.</span></label><button class="btn primary" type="submit">Done</button></form>`);return;
  }
  if(kind==='mfa-saved'){closeDialogs();toast('Authenticator updated. Other sessions were signed out.');return;}
  if(kind==='profile'){await api('/api/settings/profile',v,'PUT');await reload();toast('Sender identity saved. Existing approvals may need renewal.');return;}
  if(kind==='city'){await api('/api/cities',{name:v.name,region:v.region,country:'US',timezone:v.timezone});closeDialogs();await reload();go('cities');toast('City added to the shared catalog.');return;}
  if(kind==='client'){
   await api('/api/clients'+(id?'/'+id:''),{name:v.name,website:v.website,city_ids:new FormData(form).getAll('city_ids'),funded:!!v.funded,budget_cents:Math.round(Number(v.budget)*100),max_slots:Number(v.max_slots),offer:v.offer,renewal_terms:v.renewal_terms},id?'PUT':'POST');
   closeDialogs();await reload();go('clients');toast('Client sponsor saved.');return;
  }
  if(kind==='hunt'){await H.submit(form,reload,go);return;}
  if(kind==='review'){
   const evidence=[...form.querySelectorAll('.evidence-row')].map(row=>({url:row.querySelector('[name="evidence_url"]').value.trim(),note:row.querySelector('[name="evidence_note"]').value.trim()})).filter(x=>x.url||x.note);
   await api('/api/entities/'+id+'/review',{campaign:v.campaign,website_status:v.website_status,website_url:v.website_url,history_note:v.history_note,activity_note:v.activity_note,evidence,rights_confirmed:!!v.rights_confirmed,contact_id:v.contact_id||null,verify_contact:!!v.verify_contact,contact_role_note:v.contact_role_note,contact_source_url:v.contact_source_url});
   await reload();D.reviewSheet(state,id);toast('Review saved with evidence and timestamp.');return;
  }
  if(kind==='contact'){await api('/api/entities/'+id+'/contacts',v);document.querySelector('#modal').close();await reload();D.reviewSheet(state,id);toast('Public contact added. Review is still required.');return;}
  if(kind==='exclude'||kind==='suppress'){
   if(kind==='exclude')await api('/api/entities/'+id+'/exclude',{reason:v.reason});else await api('/api/suppressions',{entity_id:id,reason:v.reason});
   closeDialogs();await reload();toast(kind==='exclude'?'Organization excluded.':'Program-wide suppression recorded.');return;
  }
  if(kind==='reserve'){
   const cv=await api('/api/conversations',{entity_ids:JSON.parse(form.dataset.ids),client_id:v.client_id,contact_id:v.contact_id});selected.clear();closeDialogs();await reload();go('outreach');toast('Sponsor reserved. Create and review the first draft.');return;
  }
  if(kind==='research'){
   const run=await api('/api/research',{city_id:v.city_id,campaign:v.campaign,category:v.category,window:v.window,max_candidates:Number(v.max_candidates),max_tool_calls:Number(v.max_tool_calls),rights_acknowledged:!!v.rights_acknowledged});
   closeDialogs();await reload();go('research');toast(run.state==='setup_required'?'Research run saved; provider setup is required.':'Research job queued.');return;
  }
  if(kind==='report'){await api('/api/research/import',{city_id:v.city_id,campaign:v.campaign,category:v.category,title:v.title,report:v.report,rights_acknowledged:!!v.rights_acknowledged});closeDialogs();await reload();go('research');toast('Report saved for candidate extraction.');return;}
  if(kind==='source'){await api('/api/sources',{city_id:v.city_id||null,url:v.url,title:v.title,rights_note:v.rights_note,fetch_allowed:!!v.fetch_allowed});closeDialogs();await reload();toast('Source permissions recorded.');return;}
  if(kind==='retry'){await api('/api/research/'+id+'/retry',{provider_id:v.provider_id||null});document.querySelector('#modal').close();await reload();D.researchSheet(state,id);toast('Research state updated.');return;}
  if(kind==='candidates'){let data;try{data=JSON.parse(v.json);}catch{throw new Error('Enter valid JSON.');}await api('/api/research/'+id+'/import-candidates',data);closeDialogs();await reload();go('prospects');toast('Candidates imported for review. No contacts were approved.');return;}
  if(kind==='message'){await saveMessage(form);await reload();await openMessage(id);toast('Draft saved. Approval was cleared.');return;}
  if(kind==='event'){const c=state.conversations.find(x=>x.id===id),ct=state.contacts.find(x=>x.id===c.contact_id);await api('/api/events',{event_id:'manual-'+Array.from(crypto.getRandomValues(new Uint8Array(16)),x=>x.toString(16).padStart(2,'0')).join(''),email:ct.email,event_type:v.event_type,body:v.body});closeDialogs();await reload();toast('Inbound event recorded; sequence controls updated.');return;}
  if(kind==='agreement'){const p=await api('/api/projects',{conversation_id:id,entity_id:v.entity_id,authorized_by:v.authorized_by,agreement_note:v.agreement_note,scope:v.scope});closeDialogs();await reload();go('projects');toast('Website project created. Nothing was published.');return;}
  if(kind==='project'){await api('/api/projects/'+id,{...v,org_owns_domain:!!v.org_owns_domain,content_approved:!!v.content_approved},'PUT');await reload();D.projectSheet(state,id);toast('Project updated.');return;}
  if(kind==='directory'){await api('/api/projects/'+id+'/directories',{directory_url:v.directory_url,state:v.status,confirmed_url:v.confirmed_url,note:(v.directory_name? v.directory_name+': ':'')+v.note});document.querySelector('#modal').close();await reload();D.projectSheet(state,id);toast('Directory outcome recorded.');return;}
  if(kind==='reconcile'){await api('/api/messages/'+id+'/reconcile',v);document.querySelector('#modal').close();await reload();await openMessage(id);toast('Delivery reconciliation recorded.');return;}
  throw new Error('This form is not supported.');
 }catch(error){if(kind==='login')loginScreen(error.message);else fail(error);}finally{buttons.forEach(b=>b.disabled=false);}
});
document.addEventListener('change',async ev=>{
 const t=ev.target;
 if(t.dataset.select){t.checked?selected.add(t.dataset.select):selected.delete(t.dataset.select);renderPage();}
 if(t.dataset.filter&&t.dataset.filter!=='query'){filters[t.dataset.filter]=t.value;renderPage();}
 if(t.name==='contact_id'&&t.closest('[data-form="review"]')){const ct=state.contacts.find(x=>x.id===t.value),f=t.closest('form');f.elements.contact_role_note.value=ct?.role_note||'';f.elements.contact_source_url.value=ct?.source_url||'';f.elements.verify_contact.checked=false;}
 if(t.name==='report_file'&&t.files?.[0]){try{if(t.files[0].size>300000)throw new Error('Use a text report smaller than 300 KB.');const text=await t.files[0].text();const f=t.closest('form');f.elements.report.value=text;if(!f.elements.title.value)f.elements.title.value=t.files[0].name;}catch(error){fail(error);}}
});
let searchTimer;document.addEventListener('input',ev=>{if(ev.target.dataset.filter==='query'){filters.query=ev.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>{renderPage();const t=document.querySelector('#prospect-search');t?.focus();},160);}});
window.addEventListener('hashchange',()=>{route=currentRoute();document.body.classList.remove('nav-open');closeDialogs();render();window.scrollTo(0,0);});
document.querySelector('#modal').addEventListener('close',()=>{pendingMfa=null;});
window.addEventListener('unhandledrejection',ev=>{ev.preventDefault();fail(ev.reason instanceof Error?ev.reason:new Error('Unexpected application error.'));});
// Do not replace forms or dialogs while an operator is editing them.
setInterval(async()=>{if(user&&!settingUp&&!document.hidden&&!document.querySelector('dialog[open]')&&!document.activeElement?.matches('input,textarea,select')&&route!=='settings'){try{await reload();}catch(error){if(error.status===401)fail(error);}}},30000);
init();
