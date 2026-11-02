export const escape = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const label = (value) => String(value ?? '').replaceAll('_',' ').replace(/\b\w/g, c => c.toUpperCase());
export const date = (value) => value ? new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric'}).format(new Date(value)) : 'Not reviewed';
export const time = (value) => value ? new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(value)) : '—';
export const money = (cents) => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format((cents || 0)/100);
export const shortCategory = (value) => ({neighborhood_association:'Neighborhood association',legacy_civic_club:'Legacy civic club',cultural_veteran_or_specialized_organization:'Cultural & community',cultural_veteran:'Cultural & veteran',specialized_nonprofit:'Specialized nonprofit',historical_preservation:'Historical & preservation'}[value] || label(value));
export const websiteLabels = {unknown:'Not verified',official_website_found:'Existing website',hosted_chapter_page_only:'Chapter page only',social_only:'Social only',no_site_found_after_checks:'No site found after checks',broken_or_parked:'Broken / parked site'};
const paths = {
 grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
 search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
 pin:'<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
 building:'<path d="M4 21V5l8-3v19M12 8h8v13M2 21h20M7 7v1m0 3v1m0 3v1m9-4v1m0 3v1"/>',
 users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/><circle cx="9" cy="7" r="4"/>',
 mail:'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
 globe:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c5 5 5 13 0 18M12 3c-5 5-5 13 0 18"/>',
 settings:'<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"/><path d="m9 3 1-1h4l1 3 3 1 3 2-1 3 1 3-2 3-3 1-1 3h-5l-1-3-3-1-3-2 1-3-1-3 2-3 3-1Z"/>',
 plus:'<path d="M12 5v14M5 12h14"/>',
 arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
 chevron:'<path d="m9 5 7 7-7 7"/>',
 down:'<path d="m6 9 6 6 6-6"/>',
 check:'<path d="m5 12 4 4L19 6"/>',
 clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
 shield:'<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4Z"/><path d="m8 12 3 3 5-6"/>',
 link:'<path d="m10 13 4-4M7 14l-2 2a4 4 0 0 0 6 6l4-4a4 4 0 0 0 0-6M17 10l2-2a4 4 0 0 0-6-6L9 6a4 4 0 0 0 0 6"/>',
 download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
 external:'<path d="M14 3h7v7m0-7L10 14M10 3H4v17h17v-6"/>',
 close:'<path d="m6 6 12 12M18 6 6 18"/>',
 pause:'<path d="M8 5v14M16 5v14"/>',
 play:'<path d="m8 4 12 8-12 8Z"/>',
 file:'<path d="M14 2H5v20h14V7l-5-5Zm0 0v6h5M8 12h8m-8 4h6"/>',
 alert:'<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3v.1"/>',
 menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
 edit:'<path d="m16 3 5 5L9 20l-6 1 1-6L16 3Zm-2 2 5 5"/>',
 inbox:'<path d="M3 4h18v16H3V4Zm0 10h5l2 3h4l2-3h5"/>',
 spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
 lock:'<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
 history:'<path d="M3 10a9 9 0 1 1 2 8M3 3v7h7M12 7v6l3 2"/>',
 filter:'<path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z"/>',
 refresh:'<path d="M20 7v5h-5M4 17v-5h5M20 12a8 8 0 0 0-14-6M4 12a8 8 0 0 0 14 6"/>'
};
export const icon = (name, cls='') => `<svg class="icon ${escape(cls)}" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]||paths.file}</svg>`;
export function badge(state, text) {
 const tone = ['qualified','completed','verified','live','maintenance','sent','approved'].includes(state)?'green':['excluded','suppressed','cancelled','failed','delivery_unknown'].includes(state)?'red':['review','unknown','unverified','setup_required','draft','submission_unknown','polling_paused'].includes(state)?'amber':['researching','submitting','extracting','queued','reserved','contacted','replied','partnered'].includes(state)?'blue':'neutral';
 return `<span class="badge ${tone}"><span class="badge-dot"></span>${escape(text || (state==='review'?'Needs review':label(state)))}</span>`;
}
export const option = (value,text,selected) => `<option value="${escape(value)}" ${String(value)===String(selected)?'selected':''}>${escape(text)}</option>`;
export const field = (name,title,control,help='') => `<label class="field" for="${escape(name)}"><span>${escape(title)}</span>${control}${help?`<small>${escape(help)}</small>`:''}</label>`;
export const input = (name,value='',type='text',extra='') => `<input id="${escape(name)}" name="${escape(name)}" type="${escape(type)}" value="${escape(value)}" ${extra}>`;
export const textarea = (name,value='',rows=3,extra='') => `<textarea id="${escape(name)}" name="${escape(name)}" rows="${rows}" ${extra}>${escape(value)}</textarea>`;
export const select = (name,options) => `<select id="${escape(name)}" name="${escape(name)}">${options}</select>`;
export const check = (name,text,checked=false,help='') => `<label class="checkbox-line"><input name="${escape(name)}" type="checkbox" ${checked?'checked':''}><span>${escape(text)}${help?`<small>${escape(help)}</small>`:''}</span></label>`;
export const button = (text,action,ic='',cls='secondary',id='',extra='') => `<button class="btn ${cls}" data-action="${escape(action)}" ${id?`data-id="${escape(id)}"`:''} ${extra}>${ic?icon(ic):''}${escape(text)}</button>`;
export const external = (url,text) => /^https?:\/\//i.test(url || '') ? `<a href="${escape(url)}" target="_blank" rel="noopener noreferrer" class="text-link">${escape(text)}${icon('external')}</a>` : escape(text);
export const empty = (ic,title,text,cta='') => `<div class="empty-state"><div class="empty-icon">${icon(ic)}</div><h3>${escape(title)}</h3><p>${escape(text)}</p>${cta}</div>`;
export function toast(message,error=false) {
 const el=document.createElement('div'); el.className='toast'+(error?' error':''); el.setAttribute('role',error?'alert':'status');
 const body=document.createElement('span');body.textContent=message;el.append(body);
 const close=document.createElement('button');close.type='button';close.setAttribute('aria-label','Dismiss notification');close.innerHTML=icon('close');close.onclick=()=>el.remove();el.append(close);
 document.querySelector('#toasts').append(el);setTimeout(()=>el.remove(),error?14000:5000);
}
export function dialog(kind,title,subtitle,content,wide=false) {
 const el=document.querySelector(kind==='sheet'?'#sheet':'#modal');
 el.classList.toggle('wide',wide);
 el.querySelector('div').innerHTML=`<header class="dialog-header"><div><h2 id="${kind}-title">${escape(title)}</h2>${subtitle?`<p>${escape(subtitle)}</p>`:''}</div><button class="icon-btn" data-action="close-${kind}" aria-label="Close dialog">${icon('close')}</button></header>${content}`;
 el.setAttribute('aria-labelledby',`${kind}-title`);
 if(!el.open)el.showModal();
}
export function closeDialogs() {document.querySelectorAll('dialog[open]').forEach(el=>el.close());}
export const warning = (title,items=[]) => `<div class="notice amber">${icon('alert')}<div><strong>${escape(title)}</strong>${items.length?`<ul>${items.map(x=>`<li>${escape(x)}</li>`).join('')}</ul>`:''}</div></div>`;
