'use strict';
const LocalOCR = (() => {
 const cdn = 'https://cdn.jsdelivr.net/npm/';
 const api = cdn+'tesseract.js@6.0.1/dist/';
 let library;
 function load() {
  if (!library) library = new Promise((resolve, reject) => {
   const script = document.createElement('script');
   script.src = api+'tesseract.min.js';
   script.onload = resolve;
   script.onerror = () => {library=null;reject(Error('文字認識エンジンを取得できませんでした。'));};
   document.head.append(script);
  });
  return library;
 }
 async function read(jobs, progress) {
  const readings = [];
  let worker, expired=false, timer, warning='';
  const work = async () => {
   await load();
   if (expired) return;
   worker = await Tesseract.createWorker('jpn',1,{
    workerPath:api+'worker.min.js',corePath:cdn+'tesseract.js-core@6.0.0',
    langPath:cdn+'@tesseract.js-data/jpn@1.0.0/4.0.0_best_int',cacheMethod:'none',
    errorHandler:()=>{}
   });
   if(expired){await worker.terminate();return;}
   for (const [i,job] of jobs.entries()){
    progress('画像の文字を読み取っています（'+(i+1)+' / '+jobs.length+'頁）。');
    const {data}=await worker.recognize('data:image/png;base64,'+job.image);
    if(expired) break;
    if(data.confidence>=55 && data.text.trim()) readings.push({id:job.id,page:job.page,text:data.text});
   }
  };
  try{
   await Promise.race([work(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('文字認識は時間上限に達しました。')),120000);})]);
  }catch{warning='画像の文字認識を一部完了できませんでした。読み取れた資料からExcelを作成しました。';}
  finally{expired=true;clearTimeout(timer);if(worker)await worker.terminate().catch(()=>{});}
  return {readings,warning};
 }
 return {read};
})();
