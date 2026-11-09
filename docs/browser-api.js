'use strict';
// Same frontend API shapes; there is no HTTP API and no persistent file store.
const BrowserAPI=(()=>{
 let worker=null,sequence=0,ready=null;const pending=new Map();
 function stop(message){if(worker)worker.terminate();worker=null;ready=null;for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error(message));}pending.clear();}
 function request(data,timeout=60000){
  if(!worker){worker=new Worker('./worker.js');worker.onmessage=({data:r})=>{const p=pending.get(r.id);if(!p)return;pending.delete(r.id);clearTimeout(p.timer);r.ok?p.resolve(r.data):p.reject(Error(r.error||'処理できませんでした。'));};worker.onerror=()=>stop('読取エンジンが停止しました。入力を保持しています。もう一度操作してください。');}
  const id=++sequence;
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>stop('処理時間の上限を超えました。資料を分けて再実行してください。'),timeout);pending.set(id,{resolve,reject,timer});worker.postMessage({id,...data});});
 }
 async function init(){if(!ready)ready=request({action:'init'},180000).catch(e=>{stop(e.message);throw e;});return ready;}
 async function config(){const r=await fetch('./config.json',{cache:'no-cache'});if(!r.ok)throw Error('設定の読込に失敗しました。');return r.json();}
 async function call(path,options={}){
  if(path==='/api/session')return new Response('{"authenticated":true}');
  await init();let result;
  if(path==='/api/extract'){
   const form=options.body, files=form.getAll('files'),kinds=JSON.parse(form.get('kinds')||'[]');
   if(form.get('use_ai')==='true')throw Error('AIは未接続です。');
   if(files.length>10||files.reduce((n,f)=>n+f.size,0)>25*1024*1024)throw Error('資料は最大10点・合計25MBまでです。');
   const items=[];for(let i=0;i<files.length;i++){if(files[i].size>8*1024*1024)throw Error('資料は1点8MBまでです。');const bytes=new Uint8Array(await files[i].arrayBuffer());let binary='';for(let offset=0;offset<bytes.length;offset+=16384)binary+=String.fromCharCode(...bytes.subarray(offset,offset+16384));items.push({name:files[i].name,kind:kinds[i],raw_b64:btoa(binary)});}
   result=await request({action:'extract',files:items,text:String(form.get('text')||'')});
  }else if(path==='/api/rentroll/calculate'){
   result=await request({action:'calculate',payload:JSON.parse(options.body)});
  }else if(path==='/api/export'){
   result=await request({action:'export',payload:JSON.parse(options.body)});
   const bytes=Uint8Array.from(atob(result.xlsx),c=>c.charCodeAt(0));
   return new Response(bytes,{headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}});
  }else throw Error('この版では利用できない操作です。');
  return new Response(JSON.stringify(result),{headers:{'Content-Type':'application/json'}});
 }
 return {init,config,call,reset:()=>stop('新しい物件に切り替えました。')};
})();
