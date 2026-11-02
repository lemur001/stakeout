import {api} from './api.js';
import {escape as e,field,input,select,option} from './ui.js';

const states={AL:'Alabama',AK:'Alaska',AZ:'Arizona',AR:'Arkansas',CA:'California',CO:'Colorado',CT:'Connecticut',DE:'Delaware',DC:'District of Columbia',FL:'Florida',GA:'Georgia',HI:'Hawaii',ID:'Idaho',IL:'Illinois',IN:'Indiana',IA:'Iowa',KS:'Kansas',KY:'Kentucky',LA:'Louisiana',ME:'Maine',MD:'Maryland',MA:'Massachusetts',MI:'Michigan',MN:'Minnesota',MS:'Mississippi',MO:'Missouri',MT:'Montana',NE:'Nebraska',NV:'Nevada',NH:'New Hampshire',NJ:'New Jersey',NM:'New Mexico',NY:'New York',NC:'North Carolina',ND:'North Dakota',OH:'Ohio',OK:'Oklahoma',OR:'Oregon',PA:'Pennsylvania',RI:'Rhode Island',SC:'South Carolina',SD:'South Dakota',TN:'Tennessee',TX:'Texas',UT:'Utah',VT:'Vermont',VA:'Virginia',WA:'Washington',WV:'West Virginia',WI:'Wisconsin',WY:'Wyoming'};
const zones=['America/New_York','America/Chicago','America/Denver','America/Phoenix','America/Los_Angeles','America/Anchorage','Pacific/Honolulu'];
const regionCode=value=>Object.entries(states).find(([code,name])=>[code.toLowerCase(),name.toLowerCase()].includes((value||'').trim().toLowerCase()))?.[0]||'';
const defaultZone=region=>region==='AK'?'America/Anchorage':region==='HI'?'Pacific/Honolulu':region==='AZ'?'America/Phoenix':
 ['CA','NV','OR','WA'].includes(region)?'America/Los_Angeles':['CO','ID','MT','NM','UT','WY'].includes(region)?'America/Denver':
 ['AL','AR','IL','IA','KS','LA','MN','MS','MO','NE','ND','OK','SD','TN','TX','WI'].includes(region)?'America/Chicago':'America/New_York';
const nameKey=value=>value.trim().toLowerCase().replace(/[^\p{L}\p{N}_\s]/gu,' ').replace(/\s+/g,' ').trim();

export function locationFields(s,cityId=''){
 const city=s.cities.find(c=>c.id===cityId),region=regionCode(city?.region);
 const names=[...new Set(s.cities.map(c=>c.name))];
 return `<section data-search-location><div class="form-grid">${field('search_city','City',input('search_city',city?.name||'','text','required minlength="2" maxlength="100" placeholder="e.g. Chicago" autocomplete="address-level2" list="search-city-suggestions"'))}${field('search_state','State',select('search_state',option('','Choose state',region)+Object.entries(states).map(([code,name])=>option(code,`${name} (${code})`,region)).join('')).replace('<select ','<select required aria-label="State" autocomplete="address-level1" '))}</div><datalist id="search-city-suggestions">${names.map(name=>`<option value="${e(name)}"></option>`).join('')}</datalist><p class="muted">Search any US city. You don’t need to add it to the workspace first.</p><details><summary>Outreach timing (optional)</summary>${field('search_timezone','Scheduling timezone',select('search_timezone',option('','Use the state’s default',city?.timezone||'')+zones.map(zone=>option(zone,zone,city?.timezone||'')).join('')),'Only used for later outreach scheduling, not discovery. Some states span multiple time zones. Existing city settings are preserved.')}</details></section>`;
}

export async function resolveCity(form,s){
 const values=new FormData(form),name=String(values.get('search_city')||'').trim(),region=String(values.get('search_state')||'');
 if(name.length<2||!states[region])throw new Error('Enter a city and choose its state.');
 const existing=s.cities.find(c=>nameKey(c.name)===nameKey(name)&&regionCode(c.region)===region);
 if(existing)return existing.id;
 const city=await api('/api/cities',{name,region,country:'US',timezone:values.get('search_timezone')||defaultZone(region)});
 return city.id;
}
