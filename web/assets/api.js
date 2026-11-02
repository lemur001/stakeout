let csrf='';
export const setCsrf=value=>{csrf=value||'';};
export async function api(path,body,method){
 const options={method:method||(body===undefined?'GET':'POST'),headers:{'Accept':'application/json'},credentials:'same-origin'};
 if(body!==undefined){options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=csrf;options.body=JSON.stringify(body);}
 const response=await fetch(path,options);
 let data;try{data=await response.json();}catch{throw new Error(`The server returned ${response.status}. Refresh and check the application log.`);}
 if(!response.ok){const error=new Error((data.error||'Request failed')+(data.details?.length?'\n'+data.details.join('\n'):''));error.status=response.status;throw error;}
 return data;
}
