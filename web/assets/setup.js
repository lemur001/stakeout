import {api,setCsrf} from './api.js';
import {escape as e,icon} from './ui.js';

// Credentials live only in this form and memory until submitted. Never use browser storage.
export async function showSetup(root,{newAdmin=false,onSession,onDone}) {
 let step=0,account=null,enrollment=null,recovery=[],summary=null,checklist=null;
 const titles=['Secure your account','Agency identity','Research connections','Email connections','Ready to work'];
 const input=(name,label,value='',type='text',extra='')=>`<label class="field"><span>${e(label)}</span><input name="${e(name)}" type="${e(type)}" value="${e(value)}" ${extra}></label>`;
 const check=(name,label,checked=false)=>`<label class="checkbox-line"><input name="${name}" type="checkbox" ${checked?'checked':''}><span>${e(label)}</span></label>`;
 const submit=(label='Save and continue')=>`<button class="btn primary" type="submit">${label} ${icon('arrow')}</button>`;
 const skip=()=>'<button class="btn ghost" type="button" data-setup-click="skip">Set up later</button>';
 const secret=(name,label)=>input(name,label,'','password',`autocomplete="new-password" maxlength="4096" placeholder="${summary?.secrets_set[name]?'Saved — leave blank to keep':'Not configured'}"`)+
   (summary?.secrets_set[name]?check('clear_'+name,'Remove saved '+label.toLowerCase()):'');
 const link=(url,text)=>`<a class="text-link" href="${url}" target="_blank" rel="noopener noreferrer">${text} ${icon('external')}</a>`;
 function frame(content,sub='') {
  root.innerHTML=`<main class="setup-layout"><header class="setup-brand">${icon('shield')}<strong>Stakeout Civic</strong><span>Workspace setup</span></header><div class="setup-grid"><aside class="setup-steps" aria-label="Setup progress">${titles.map((t,i)=>`<div class="setup-step ${i===step?'current':''}" ${i===step?'aria-current="step"':''}><span>${i+1}</span>${e(t)}</div>`).join('')}<p>Secrets are encrypted before they reach the database. Your encryption key stays in Railway.</p></aside><section class="panel setup-card"><header><p class="eyebrow">Step ${step+1} of 5</p><h1>${titles[step]}</h1><p>${e(sub)}</p></header><div class="setup-error" role="alert" tabindex="-1" hidden></div>${content}</section></div></main>`;
 }
 function claim() {
  frame(`<form data-setup="claim">${input('setup_token','One-time setup token','','password','required autocomplete="off" maxlength="256"')}<p class="muted">Use the SETUP_TOKEN you saved when creating your Railway service. Only the token holder can claim this workspace.</p>${input('name','Your name','','text','required maxlength="150"')}${input('email','Sign-in email','','email','required autocomplete="username"')}${input('password','Choose a strong password','','password','required minlength="16" maxlength="512" autocomplete="new-password"')}${input('confirm','Confirm password','','password','required minlength="16" maxlength="512" autocomplete="new-password"')}<p class="muted">Use a unique passphrase of at least 16 characters, saved in your password manager.</p>${submit('Set up two-factor authentication')}</form>`,'Create your private administrator account.');
 }
 function mfaForm() {
  frame(`<form data-setup="mfa"><p>In your authenticator app, add an account using a setup key. Choose <strong>time-based</strong> and name it Stakeout Civic.</p><label class="field"><span>Authenticator setup key</span><input class="setup-secret" readonly value="${e(enrollment.secret)}" aria-label="Authenticator setup key"></label><p class="muted">Keep this key private. Setup expires in 15 minutes.</p>${input('code','Six-digit authenticator code','','text','required inputmode="numeric" pattern="[0-9]{6}" autocomplete="one-time-code" maxlength="6"')}${submit(newAdmin?'Create secure account':'Enable two-factor authentication')}</form>`,'A password and an authenticator code protect each sign-in.');
 }
 function recoveryScreen() {
  frame(`<form data-setup="recovery"><div class="notice amber"><div><strong>Save your recovery codes now.</strong><p>Each code works once if you lose your authenticator. These codes are shown only once.</p></div></div><pre class="recovery-codes">${recovery.map(e).join('\n')}</pre><button type="button" class="btn secondary" data-setup-click="download">Download recovery codes</button>${check('saved','I saved these codes in a secure password manager.')}<p class="muted">Your one-time Railway setup token can now be removed. Keep ENCRYPTION_KEY and APP_SECRET.</p>${submit('Continue')}</form>`,'Your administrator account is protected.');
 }
 async function render() {
  if(step===0){
   if(newAdmin)return claim();
   checklist=await api('/api/setup/checklist');
   if(checklist.production&&checklist.mfa_enabled&&!checklist.elevated)return frame(`<form data-setup="reauth">${input('password','Current password','','password','required autocomplete="current-password"')}${input('code','Authenticator or recovery code','','text','required autocomplete="one-time-code" maxlength="64"')}${submit('Unlock connection settings')}</form>`,'Confirm it is you before changing saved credentials.');
   if(checklist.mfa_enabled||!checklist.production){step=1;return render();}
   return frame(`<form data-setup="enroll-existing">${input('password','Current password','','password','required autocomplete="current-password"')}${submit('Set up authenticator')}</form>`,'Protect your existing administrator account with two-factor authentication.');
  }
  if(!checklist)checklist=await api('/api/setup/checklist');
  if(step===1){const p=checklist.profile;return frame(`<form data-setup="profile">${input('agency_name','Agency name',p.agency_name,'text','required maxlength="150"')}${input('sender_name','Sender name',p.sender_name,'text','required maxlength="150"')}${input('sender_email','Sender email',p.sender_email,'email','maxlength="320"')}<label class="field"><span>Business postal address</span><textarea name="postal_address" maxlength="400" rows="3">${e(p.postal_address)}</textarea></label><p class="muted">You can add the email and postal address later. Both are required before sending outreach.</p>${submit()}</form>`,'The identity your recipients will see.');}
  summary=await api('/api/settings/integrations');const v=summary.values;
  if(step===2)return frame(`<form data-setup="research"><p>Connect your own accounts for automated research. You can use the workspace and import reports without them.</p><div class="setup-links">${link('https://aistudio.google.com/api-keys','Get a Gemini API key')}${link('https://api-dashboard.search.brave.com/','Get a Brave Search API key')}</div>${secret('gemini_api_key','Gemini API key')}${secret('brave_key','Brave Search API key')}<h2>Prospect discovery connections</h2><p>Public inventory and site checks do not need these keys. DataForSEO search and backlinks run only with a hunt budget you approve.</p>${secret('dataforseo_login','DataForSEO API login')}${secret('dataforseo_password','DataForSEO API password')}${secret('opr_key','Open PageRank API key')}<h2>AI research models</h2>${input('research_agent','Gemini research agent',v.research_agent,'text','required')}${input('extraction_model','Gemini extraction model',v.extraction_model,'text','required')}<p class="muted">Model availability depends on your provider account. Saved credentials have not been tested with the provider. Review billing and source permissions before running research.</p>${check('source_rights_approved','I confirmed permission to retrieve and retain the source content.',v.source_rights_approved)}${check('brave_storage_rights','My Brave plan permits storing search results.',v.brave_storage_rights)}${input('daily_research_limit','Daily research job limit',v.daily_research_limit,'number','min="1" max="100" required')}<div class="form-actions">${skip()}${submit()}</div></form>`,'Optional. Enter credentials here over your secure connection.');
  if(step===3)return frame(`<form data-setup="mail"><p>Use your mail provider’s authenticated SMTP and IMAP settings. Prefer a dedicated mailbox and app passwords. Both connections require TLS.</p><h2>Outgoing mail</h2>${input('smtp_host','SMTP hostname',v.smtp_host)}${input('smtp_port','SMTP port',v.smtp_port,'number','required min="1" max="65535"')}${check('smtp_ssl','Use implicit TLS (usually port 465). Otherwise require STARTTLS.',v.smtp_ssl)}${input('smtp_user','SMTP username',v.smtp_user,'text','autocomplete="off"')}${secret('smtp_password','SMTP password')}${input('smtp_from','From email',v.smtp_from,'email')}<h2>Reply monitoring</h2>${input('imap_host','IMAP hostname',v.imap_host)}${input('imap_port','IMAP TLS port',v.imap_port,'number','required min="1" max="65535"')}${input('imap_user','IMAP username',v.imap_user,'text','autocomplete="off"')}${secret('imap_password','IMAP password')}${input('imap_mailbox','Mailbox folder',v.imap_mailbox,'text','required')}<details><summary>Optional signed delivery webhook</summary>${secret('webhook_secret','Webhook signing secret')}<p class="muted">Only configure this if your provider adapter uses the Stakeout signed webhook format. It does not replace IMAP.</p></details>${check('provider_approved','My provider permits this outreach.',v.provider_approved)}${check('sender_auth_confirmed','I verified SPF, DKIM and DMARC for my sending domain.',v.sender_auth_confirmed)}${input('daily_send_limit','Daily send ceiling',v.daily_send_limit,'number','required min="1" max="100"')}<div class="notice muted-notice"><div>Saving credentials pauses outreach. Live sending also requires ALLOW_LIVE_SEND=true in Railway, current message approvals, and a healthy reply connection.</div></div><div class="form-actions">${skip()}${submit()}</div></form>`,'Optional. Your mailbox passwords will never be returned to the browser.');
  checklist=await api('/api/setup/checklist');
  frame(`<form data-setup="complete"><ul class="setup-checks">${[['https','HTTPS configured'],['encrypted_storage','Credential encryption configured'],['mfa','Two-factor authentication enabled'],['identity','Agency identity saved']].map(([key,label])=>`<li>${icon(checklist.checks[key]?'check':'alert')} ${label}: <strong>${checklist.checks[key]?'Ready':'Needs attention'}</strong></li>`).join('')}</ul><h2>Optional connections</h2><p>These checks confirm configuration, not provider acceptance. Your first live job and mailbox connection still need verification.</p>${['research_readiness','email_readiness'].map(k=>`<details><summary>${k==='research_readiness'?'Research':'Email'}: ${summary[k].length?'setup remaining':'configured'}</summary><ul>${summary[k].map(x=>`<li>${e(x)}</li>`).join('')||'<li>Configuration present; test with your provider.</li>'}</ul></details>`).join('')}<p>Back up your database and keep a separate, secure copy of ENCRYPTION_KEY and APP_SECRET. Losing the encryption key makes saved credentials and authenticator secrets unrecoverable.</p><p>Outreach will remain paused when you finish.</p>${submit('Open workspace')}</form>`,'Your workspace is ready for review.');
 }
 function error(err){const el=root.querySelector('.setup-error');if(el){el.textContent=err.message;el.hidden=false;el.focus();}}
 async function submitted(ev){
  const f=ev.target;if(!f.matches('[data-setup]'))return;ev.preventDefault();if(!f.reportValidity())return;
  const v=Object.fromEntries(new FormData(f)),kind=f.dataset.setup,buttons=f.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
  try{
   if(kind==='claim'){
    if(v.password!==v.confirm)throw new Error('Passwords do not match.');
    enrollment=await api('/api/setup/enrollment',{setup_token:v.setup_token,email:v.email});
    account={setup_token:v.setup_token,name:v.name,email:v.email,password:v.password};mfaForm();return;
   }
   if(kind==='enroll-existing'){enrollment=await api('/api/security/mfa/enrollment',{password:v.password});account={password:v.password};mfaForm();return;}
   if(kind==='reauth'){await api('/api/security/reauth',v);step=1;await render();return;}
   if(kind==='mfa'){
    const result=newAdmin?await api('/api/setup/bootstrap',{...account,enrollment:enrollment.enrollment,code:v.code}):await api('/api/security/mfa/confirm',{password:account.password,enrollment:enrollment.enrollment,new_code:v.code});
    account=null;enrollment=null;setCsrf(result.csrf);onSession(result);recovery=result.recovery_codes;recoveryScreen();return;
   }
   if(kind==='recovery'){if(!v.saved)throw new Error('Save your recovery codes and check the confirmation.');recovery=[];newAdmin=false;step=1;await render();return;}
   if(kind==='profile'){await api('/api/settings/profile',v,'PUT');checklist=null;step=2;await render();return;}
   if(kind==='research'||kind==='mail'){
    const payload={...v,clear_secrets:[]};
    const bools=kind==='research'?['source_rights_approved','brave_storage_rights']:['smtp_ssl','provider_approved','sender_auth_confirmed'];
    bools.forEach(k=>payload[k]=!!v[k]);
    ['daily_research_limit','daily_send_limit','smtp_port','imap_port'].forEach(k=>{if(k in payload)payload[k]=Number(payload[k]);});
    for(const k of Object.keys(payload))if(k.startsWith('clear_')&&k!=='clear_secrets'){if(payload[k])payload.clear_secrets.push(k.slice(6));delete payload[k];}
    await api('/api/settings/integrations',payload,'PUT');f.reset();step++;await render();return;
   }
   if(kind==='complete'){await api('/api/setup/complete',{});cleanup();await onDone();}
  }catch(err){error(err);}finally{buttons.forEach(b=>b.disabled=false);}
 }
 async function clicked(ev){
  const target=ev.target.closest('[data-setup-click]');if(!target)return;
  try{
   if(target.dataset.setupClick==='skip'){target.disabled=true;step++;await render();}
   if(target.dataset.setupClick==='download'){
    const url=URL.createObjectURL(new Blob(['Stakeout Civic recovery codes — store privately. Each code works once.\n\n'+recovery.join('\n')],{type:'text/plain'}));
    const a=document.createElement('a');a.href=url;a.download='stakeout-recovery-codes.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
   }
  }catch(err){error(err);}
 }
 function cleanup(){account=null;enrollment=null;recovery=[];root.removeEventListener('submit',submitted);root.removeEventListener('click',clicked);}
 root.addEventListener('submit',submitted);root.addEventListener('click',clicked);
 await render();
}
