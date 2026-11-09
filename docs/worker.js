const APP_SHA="ca8ea4cc90aae625f964a98defbf0c8583136fbe2756187f678c0b318a43e424";
'use strict';
// No uploaded data is used in URLs or outbound requests. All processing is in RAM.
const runtimeURL='https://cdn.jsdelivr.net/pyodide/v0.29.3/full/';
let pythonReady;
async function initialize(){
  importScripts(runtimeURL+'pyodide.js');
  const py=await loadPyodide({indexURL:runtimeURL,stdout:()=>{},stderr:()=>{}});
  await py.loadPackage('pillow');
  const response=await fetch('./application.zip',{cache:'no-cache'});
  if(!response.ok)throw Error('アプリ本体を読み込めませんでした。');
  const archive=new Uint8Array(await response.arrayBuffer());
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',archive))).map(b=>b.toString(16).padStart(2,'0')).join('');
  if(digest!==APP_SHA)throw Error('アプリ本体の照合値が一致しません。再読み込みしてください。');
  py.unpackArchive(archive,'zip',{extractDir:'/app'});
  py.runPython("import sys; sys.path.insert(0, '/app'); from browser_backend import dispatch");
  return py;
}
self.onmessage=async({data})=>{
  try{
    pythonReady=pythonReady||initialize();
    const py=await pythonReady;
    if(data.action==='init'){self.postMessage({id:data.id,ok:true,data:{ready:true}});return;}
    py.globals.set('_request_json',JSON.stringify(data));
    let result;
    try{result=JSON.parse(py.runPython('dispatch(_request_json)'));}
    finally{py.globals.delete('_request_json');py.runPython('import gc; gc.collect()');}
    self.postMessage({id:data.id,...result});
  }catch(e){pythonReady=null;self.postMessage({id:data.id,ok:false,error:'読取エンジンを起動できませんでした。通信を確認して再読込してください。 '+String(e.message||e).slice(0,120)});}
};
