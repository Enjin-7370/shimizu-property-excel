'use strict';
// A convenience entrance lock for a public, browser-only utility.
// It does not restrict access to public source files and is not server authentication.
(()=>{
 const form=document.getElementById('entryForm'),password=document.getElementById('entryPassword'),message=document.getElementById('entryMessage'),button=document.getElementById('entrySubmit');
 const expected='6749cc426d5c6b9e48e048a52513bccec39b8d63d1626fd60c436b026b22929d';
 let loaded=false;
 function script(src){return new Promise((resolve,reject)=>{const el=document.createElement('script');el.src=src;el.async=false;el.onload=resolve;el.onerror=()=>reject(Error('画面の読込に失敗しました。再読み込みしてください。'));document.body.append(el);});}
 form.addEventListener('submit',async event=>{
  event.preventDefault();button.disabled=true;message.textContent='';
  try{
   const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(password.value)))).map(x=>x.toString(16).padStart(2,'0')).join('');
   password.value='';
   if(digest!==expected){message.textContent='パスワードが違います。';password.focus();return;}
   if(!loaded){await Promise.all([script('./browser-api.js'),script('./ocr.js')]);await Promise.all([script('./app.js'),script('./rentroll.js')]);loaded=true;}
   document.getElementById('entryGate').remove();document.getElementById('workspaceApp').hidden=false;
   document.querySelector('h1').focus();
  }catch(e){message.textContent=e.message||'画面を開けませんでした。再読み込みしてください。';}
  finally{button.disabled=false;}
 });
})();
