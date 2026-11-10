'use strict';
const $=s=>document.querySelector(s);
let pendingAI=null;try{const saved=JSON.parse(sessionStorage.getItem('shimizu-pending-ai-operation')||'null');if(saved&&typeof saved.id==='string'&&/^[-a-f0-9]{36}$/.test(saved.id))pendingAI=saved;}catch{}
let config=null, files=[], evidence={}, sources=[], token='', loggedIn=false, busy=false, touched=new Set(), caseRevision=0;
let lastReview=null, feedback=[], readyUrl='', readyFields='', draftEpoch=0, editTimer;
const draftInfo=t=>{$('#draftInfo').textContent=t;};
function discardDraft(){
 ++draftEpoch;
 clearTimeout(editTimer);
 if(readyUrl)URL.revokeObjectURL(readyUrl);
 readyUrl='';readyFields='';
 const link=$('#readyFile');link.hidden=true;link.removeAttribute('href');
}
function clearDelivery(){
 discardDraft();lastReview=null;feedback=[];
 $('#draftTitle').textContent='Excelの仕上がり';draftInfo('資料を追加すると、ここに物件概要書が表示されます。');
 $('#feedbackText').value='';$('#feedbackLog').replaceChildren();$('#unknowns').replaceChildren();
 $('#feedbackForm').hidden=true;$('#reviewArea').hidden=true;
}
function issueGroups(){
 const v=values(), box=$('#unknowns');box.replaceChildren();
 for(const [title,itemKeys,source] of [
  ...sections.slice(0,5).map(([name,source,keys])=>[name+'の未確認項目',keys.filter(k=>!config.manual_only.includes(k)&&!touched.has(k)),source]),
  ['担当者が指定する項目',config.manual_only],
  ['手直しで空欄にした項目',[...touched].filter(k=>!config.manual_only.includes(k))]
 ]){
  const labels=itemKeys.filter(k=>hasField(k)&&(v[k]===null||v[k]==='')).map(k=>config.fields[k].label);
  if(!labels.length)continue;
  const section=node('details');section.open=Boolean(source);
  section.append(node('summary','',title+'（'+labels.length+'）'),node('p','',labels.join(' ・ ')+(source?'　／　確認元：'+source:'')));box.append(section);
 }
}
function displayReview(){
 if(!lastReview)return;
 $('#reviewArea').hidden=false;$('#feedbackForm').hidden=false;issueGroups();
 const info=[], issues=[];
 for(const w of lastReview.warnings){
  (/入力から除外|シートを使用|数式セルは保存時/.test(w)?info:issues).push(w);
 }
 $('#warnings').replaceChildren(...issues.map(t=>node('p','warn',t)));
 if(info.length){const d=node('details');d.append(node('summary','','使用した資料・除外した見本'),...info.map(t=>node('p','',t)));$('#warnings').append(d);}

 $('#feedbackLog').replaceChildren(...feedback.map(f=>node('li','',f.text+'　｜　'+f.status)));
}
async function makeReady(){
 if(!lastReview)return;
 discardDraft();
 const epoch=draftEpoch,fields=values(),snapshot=JSON.stringify(fields);
 $('#draftTitle').textContent='Excelを作成中…';
 const r=await call('/api/export',{method:'POST',body:JSON.stringify({fields,as_of:today()})});
 const blob=await r.blob();
 if(epoch!==draftEpoch||snapshot!==JSON.stringify(values()))return;
 readyUrl=URL.createObjectURL(blob);readyFields=snapshot;
 const link=$('#readyFile');link.href=readyUrl;
 link.download=(fields.property_name||'物件').replace(/[\\/:*?"<>|]/g,'_').slice(0,90)+'_物件概要書.xlsx';link.hidden=false;
 $('#draftTitle').textContent=(fields.property_name||'物件概要書')+'のExcelができました';
 const n=Object.keys(evidence).filter(k=>!touched.has(k)).length;
 if(!n && ![...touched].some(k=>fields[k]!==null && fields[k]!=='')){
  $('#draftTitle').textContent='この資料からは物件項目を転記できませんでした';
  draftInfo('自動入力は0件です。下の確認理由を見て、同じ物件のほかの拠出資料を追加するか、指摘欄から入力できます。');link.textContent='空欄の編集用書式を取得';displayReview();return;
 }
 link.textContent='編集用Excelをダウンロード ↓';
 draftInfo('資料に根拠のある'+n+'項目を反映。空欄があっても、このまま編集用Excelを取得できます。');displayReview();
}
function refreshAfterEdit(){
 if(!lastReview||busy||readyFields===JSON.stringify(values()))return;
 discardDraft();displayReview();$('#draftTitle').textContent='編集内容を反映中…';
 editTimer=setTimeout(()=>makeReady().catch(draftFailed),250);
}
function draftFailed(e){
 discardDraft();$('#draftTitle').textContent='Excelを作成できませんでした';draftInfo(e.message);
}
function fieldCorrection(sentence){
 const clean=sentence.normalize('NFKC').trim();
 if(/[?？]/.test(clean))return null;
 const labelKeys=Object.entries(config.fields).flatMap(([k,f])=>[[f.label.normalize('NFKC'),k]]);
 labelKeys.push(['価格','price_yen'],['住所','address'],['現況年間収入','current_annual_income_yen'],['満室年間収入','full_annual_income_yen']);
 labelKeys.sort((a,b)=>b[0].length-a[0].length);
 for(const [label,key] of labelKeys){
  if(key==='handover'||!clean.startsWith(label))continue;
  const instruction=clean.slice(label.length).match(/^\s*(?:[:=]|は|を)\s*(.+)$/u);
  if(!instruction)continue;
  let value=instruction[1].trim().replace(/\s*(?:に(?:訂正|修正|変更)(?:してください)?|です)\s*$/u,'').trim();
  value=value.replace(/^「([^」]+)」$/u,'$1');
  if(value==='空欄'||value==='空白')return {key,value:''};
  if(!value||/確認|不明|かもしれ|でしょう|[。！？?]|→|(?:から|ではなく).*(?:へ|に)/u.test(value))return null;
  if(config.numeric_fields.includes(key)){
   const m=value.replace(/[,\s]/g,'').match(/^(\d+(?:\.\d+)?)(億円?|万円?|円|m2|平方メートル|%)?$/i);
   if(!m)return null;
   const unit=m[2]||'';
   if(unit && !(key.includes('yen')?/円|億|万/:key.endsWith('_pct')?/%/:/m2|平方メートル/i).test(unit))return null;
   value=Number(m[1])*(unit.startsWith('億')?1e8:unit.startsWith('万')?1e4:1);
   if(!Number.isFinite(value)||value>=1e13)return null;
  }else if(key==='transaction'&&!['媒介','代理','売主'].includes(value))return null;
  else if(value.length>(key==='remarks'?config.remarks_limit:300))return null;
  return {key,value};
 }
 return null;
}
$('#feedbackForm').addEventListener('submit',async e=>{
 e.preventDefault();
 const text=$('#feedbackText').value.trim();if(!text||!lastReview||busy)return;
 if(feedback.length>=200){toast('指摘は1物件200件までです。途中データを保存してください。');return;}
 const applied=[],pending=[];
 for(const part of text.split(/[。\n]+/u).map(s=>s.trim()).filter(Boolean)){
  const edit=fieldCorrection(part);
  if(!edit){pending.push(part);continue;}
  put(edit.key,edit.value,true);delete evidence[edit.key];updateSource(edit.key);
  applied.push(config.fields[edit.key].label);
 }
 const status=[applied.length?'Excelに反映：'+applied.join('、'):'',pending.length?'要確認として記録：'+pending.join('／'):''].filter(Boolean).join('。');
 feedback.push({text,status});$('#feedbackText').value='';displayReview();
 if(applied.length){$('#reviewed').checked=false;setBusy(true,'export');updateMetrics();try{await makeReady();}catch(e){draftFailed(e);}finally{setBusy(false);}}
 toast(status);
});
const sections=[
 ['基礎情報','住宅地図・土地謄本・レントロール',['property_name','price_yen','full_annual_income_yen','current_annual_income_yen','address','parcel_address','transport']],
 ['土地情報','土地謄本',['land_right','land_category','land_area_basis','land_area_m2','road_value_yen_m2','road_direction_width','road_type']],
 ['建物情報','建物謄本・図面・管理委託契約書',['building_type','structure','building_area_m2','built_date','units','unit_mix']],
 ['法令上の制限','対象地点の用途地域図',['zoning_area','land_use_zone','building_coverage_pct','floor_area_ratio_pct','fire_zone','height_district','min_site_area','absolute_height','other_restrictions']],
 ['その他情報','管理条件・公課・修繕・稼働状況',['handover','transaction','remarks']],
 ['会社情報','完成見本の記載を引き継ぎ・必要時のみ編集',['company_name','company_address','company_phone','agent']]
];
const wide=new Set(['property_name','address','parcel_address','transport','structure','other_restrictions','remarks','company_address']);
function toast(t){$('#toast').textContent=t;$('#toast').classList.remove('hidden');clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').classList.add('hidden'),6500);}
function showNotice(t,warning=false){$('#notice').textContent=t;$('#notice').classList.toggle('warning',warning);}
function node(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function today(){return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(new Date());}
function hasField(k){return Object.prototype.hasOwnProperty.call(config.fields,k);}
function input(key){return document.getElementById('field-'+key);}
function values(){const r={};for(const k of Object.keys(config.fields)){let v=input(k).value.trim();r[k]=config.numeric_fields.includes(k)?(v===''?null:Number(v)):v;}r.handover='相談';return r;}
function put(k,v,manual=false){const el=input(k);if(!el)return;el.value=v??'';if(manual)touched.add(k);}
function buildForm(){
 const mount=$('#formSections');mount.replaceChildren();
 sections.forEach(([name,source,keys],si)=>{
  const block=node('section','form-section');const header=node('div','section-heading');header.append(node('h2','',name),node('p','',source));block.append(header);
  const grid=node('div','field-grid');
  keys.forEach(k=>{
   const f=node('div','field'+(wide.has(k)?' wide':''));f.dataset.field=k;
   const lab=node('label','',config.fields[k].label);lab.htmlFor='field-'+k;
   if(config.manual_only.includes(k))lab.append(node('span','manual','手入力'));
   if(k==='handover')lab.append(node('span','fixed','固定'));
   let el;
   if(k==='transaction'){el=node('select');['','媒介','代理','売主'].forEach(v=>{let o=node('option','',v||'選択してください');o.value=v;el.append(o);});}
   else if(k==='remarks'){el=node('textarea');el.rows=6;el.maxLength=config.remarks_limit;el.placeholder='管理条件、税・評価額、修繕、稼働状況を、根拠のある範囲だけ簡潔に。';}
   else{el=node('input');el.type=config.numeric_fields.includes(k)?'number':'text';if(el.type==='number'){el.min='0';el.step='any';}el.maxLength=300;}
   el.id='field-'+k;el.autocomplete='off';
   if(k==='handover'){el.value='相談';el.readOnly=true;}
   if(k==='land_area_basis')el.value='公簿';
   if(config.defaults[k])el.value=config.defaults[k];
   if(k==='built_date')el.placeholder='例：2005-03 または 2005-03-31';
   if(k==='price_yen')el.placeholder='空欄のままでも出力できます';
   el.addEventListener('input',()=>{touched.add(k);delete evidence[k];$('#reviewed').checked=false;updateSource(k);updateMetrics();});
   el.addEventListener('change',()=>{touched.add(k);delete evidence[k];$('#reviewed').checked=false;updateSource(k);updateMetrics();});
   f.append(lab,el,node('div','source',''));grid.append(f);
  });
  block.append(grid);mount.append(block);
 });
 updateMetrics();
}
function updateSource(key){
 const target=document.querySelector(`[data-field="${key}"] .source`);target.replaceChildren();
 if(touched.has(key)){target.append(node('span','','手入力・編集済み（再読取では上書きしません） '));if(evidence[key]?.method!=='rentroll-reviewed')return;}
 const e=evidence[key];if(!e)return;
 const b=node('button','',e.components?`複数資料 ${e.components.length}件 — 根拠を見る`:`${e.source} · ${e.page}頁／シート — 根拠を見る`);
 b.title=e.quote;b.addEventListener('click',()=>{
   $('#sourcePanel').classList.remove('hidden');$('#sourceText').textContent=e.components?e.components.map(x=>`【${x.source} / ${x.page}】\n${x.quote}`).join('\n\n'):e.quote;
   $('#sourcePanel').open=true;$('#sourcePanel').scrollIntoView({behavior:'smooth',block:'center'});
 });target.append(b);
 if(e.method==='ai-visual')target.append(node('span','','（画像からの候補・要原本照合）'));
}
function yen(v){return v==null||v===''?'—':Number(v).toLocaleString('ja-JP')+' 円';}
function pct(inc,p){return inc!=null&&p>0?(Math.round((Number(inc)/p+Number.EPSILON)*100000)/1000).toFixed(2)+'%':'—';}
function updateMetrics(){
 if(!config)return;const v=values();
 $('#annualMetric').textContent=yen(v.current_annual_income_yen);
 $('#priceMetric').textContent=v.price_yen>0?yen(v.price_yen):'未入力';
 $('#yieldMetric').textContent=pct(v.current_annual_income_yen,v.price_yen);
 $('#count').textContent=Object.entries(v).filter(([k,x])=>x!==''&&x!==null&&!k.startsWith('company_')&&k!=='agent').length+'項目';
 $('#exportHint').textContent=v.price_yen>0?'価格変更に合わせて、利回りはExcelでも再計算されます。':'価格が空欄のため、利回りも空欄で出力します。';
 renderPreview();refreshAfterEdit();
}
function renderPreview(){
 const v=values();const paper=$('#preview');paper.replaceChildren(node('h2','','物 件 概 要 書'));
 for(const [name,,keys] of sections.slice(0,5)){
  paper.append(node('h3','','【'+name+'】'));const table=node('table');
  for(const k of keys){if(k==='land_area_basis')continue;const tr=node('tr');let val=v[k];
   if(config.numeric_fields.includes(k)&&val!=null){val=Number(val).toLocaleString('ja-JP')+(['land_area_m2','building_area_m2'].includes(k)?' ㎡':['building_coverage_pct','floor_area_ratio_pct'].includes(k)?' %':' 円');}
   tr.append(node('th','',config.fields[k].label),node('td','',val??''));table.append(tr);
   if(k==='current_annual_income_yen'){const y=node('tr');y.append(node('th','','表面利回り'),node('td','',`満室：${pct(v.full_annual_income_yen,v.price_yen)}　現況：${pct(v.current_annual_income_yen,v.price_yen)}`));table.append(y);}
  }paper.append(table);
 }
 paper.append(node('footer','',[v.company_name,v.company_address,v.company_phone,'担当：'+v.agent].filter(Boolean).join('　')));
 paper.append(node('small','','入力内容の確認用プレビューです。Excelの配置は清水さんの完成見本を使用します。未入力の欄は補完しません。'));
}
function guessKind(name){if(/レント|rent|収支明細/i.test(name))return'rentroll';if(/用途地域|都市計画/.test(name))return'zoning';if(/管理委託/.test(name))return'management';if(/固定資産|評価証明/.test(name))return'tax';if(/修繕/.test(name))return'repair';if(/土地|地積/.test(name))return'land';if(/建物.*謄本|建物.*登記/.test(name))return'building';if(/図面|間取/.test(name))return'drawing';if(/住宅地図|案内図/.test(name))return'map';if(/概要|\.txt$|\.md$/i.test(name))return'notes';return'unknown';}
function renderFiles(){
 const list=$('#fileList');list.replaceChildren();files.forEach((item,i)=>{
  const row=node('div','file-row'),title=node('div','file-title');title.append(node('span','',item.file.name));const remove=node('button','','×');remove.setAttribute('aria-label',item.file.name+'を外す');remove.addEventListener('click',()=>{if(busy)return;files.splice(i,1);renderFiles();if(files.length||$('#memo').value.trim())extract();else{clearAutoValues();clearDelivery();resetRentroll();sources=[];$('#sourcePanel').classList.add('hidden');$('#conflicts').replaceChildren();updateMetrics();}});title.append(remove);
  const select=node('select');select.setAttribute('aria-label',item.file.name+'の資料種別');Object.entries(config.types).forEach(([k,t])=>{const o=node('option','',t);o.value=k;select.append(o);});select.value=item.kind;select.disabled=busy;remove.disabled=busy;select.addEventListener('change',()=>{if(!busy){item.kind=select.value;extract();}});row.append(title,select);list.append(row);
 });
}
function addFiles(fs){
 if(busy){toast('処理中は資料を追加できません。入力は保持しています。');return;}
 let added=0;for(const f of fs){if(files.length>=10){toast('資料は10点までです。');break;}if(f.size>(/\.zip$/i.test(f.name)?25:8)*1024*1024){toast(f.name+'はファイルサイズの上限を超えています。');continue;}if(!/\.(zip|pdf|png|jpe?g|webp|xlsx|txt|md|csv)$/i.test(f.name)){toast('対応していない形式です。PDF・画像・Excel・テキスト・ZIPを選択してください。');continue;}if(files.some(x=>x.file.name===f.name&&x.file.size===f.size&&x.file.lastModified===f.lastModified)){toast('同じ添付は追加していません。');continue;}files.push({file:f,kind:guessKind(f.name)});added++;}
 renderFiles();$('#files').value='';if(added)extract();
}
async function call(path,options={}){
 const headers={'X-Requested-With':'PropertyApp',...(options.headers||{})};if(token)headers.Authorization='Bearer '+token;
 const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),170000);
 try{const res=await fetch(path,{...options,headers,signal:controller.signal});if(!res.ok){const e=await res.json().catch(()=>({}));if(res.status===401){loggedIn=false;$('#auth').classList.remove('hidden');}const error=new Error((e.error||'処理に失敗しました。')+(e.event_id?' / ID: '+e.event_id:''));error.identity_blocked=e.identity_blocked===true;throw error;}return res;}
 catch(e){if(!config.local&&e instanceof TypeError){$('#auth').classList.remove('hidden');$('#authNote').textContent='接続または認証期限を確認できません。別タブで会社ログインを更新してから、接続を再確認してください。入力はこの画面に保持しています。';}if(e.name==='AbortError')throw Error('応答を確認できません。入力は残っています。AI読取の再実行は課金の重複を確認してから行ってください。');throw e;}
 finally{clearTimeout(timer);}
}
function setBusy(on,operation='extract'){
 busy=on;document.querySelectorAll('#formSections input,#formSections select,#formSections textarea,#feedbackSubmit').forEach(el=>{el.disabled=on;});
 document.querySelectorAll('#rentrollPanel input,#rentrollPanel select,#rentrollPanel button').forEach(el=>{el.disabled=on;});
 if(!on)$('#rentApply').disabled=!rentResult||!Object.values(rentResult.totals).some(v=>v!==null)||rentIdentityBlocked;
 for(const id of ['extract','export','newCase','loadState','stateFile','files','sample','memo','saveState'])$('#'+id).disabled=on;
 $('#useAI').disabled=on||!config.ai_ready;
 document.querySelectorAll('#fileList button,#fileList select').forEach(el=>el.disabled=on);
 $('#extract').textContent=on&&operation==='extract'?'読み取り中…':'テキスト・資料から再作成 →';
 $('#export').textContent=on&&operation==='export'?'Excel作成中…':'Excel下書きを出力';
}
function clearAutoValues(){
 for(const k of Object.keys(config.fields)){
  if(touched.has(k)||k==='handover'||k.startsWith('company_')||k==='agent')continue;
  put(k,k==='land_area_basis'?'公簿':'');delete evidence[k];updateSource(k);
 }
}
async function extract(){
 if(busy)return;if(!loggedIn){toast('先にログイン・認証設定を確認してください。');return;}
 const fd=new FormData();files.forEach(x=>fd.append('files',x.file));fd.append('kinds',JSON.stringify(files.map(x=>x.kind)));fd.append('text',$('#memo').value);fd.append('use_ai',String($('#useAI').checked));
 if($('#useAI').checked&&!config.local){pendingAI=pendingAI||{id:crypto.randomUUID()};try{sessionStorage.setItem('shimizu-pending-ai-operation',JSON.stringify(pendingAI));}catch{}fd.append('operation_id',pendingAI.id);}
 discardDraft();lastReview=null;$('#reviewArea').hidden=true;$('#feedbackForm').hidden=true;$('#draftTitle').textContent='資料を読み取り中…';draftInfo('この画面を開いたままお待ちください。');
 const revision=caseRevision;setBusy(true);showNotice('資料を読み取っています。手入力した項目は保持します。');
 try{
  const result=await (await call('/api/extract',{method:'POST',body:fd})).json();
  if(revision!==caseRevision)return;
  if(result.ai_used){pendingAI=null;try{sessionStorage.removeItem('shimizu-pending-ai-operation');}catch{}}
  const notes=[...(result.warnings||[])];
  acceptRentTables(result.rentroll_tables||[],result.identity_blocked);
  clearAutoValues();
  for(const [k,v] of Object.entries(result.fields)){
   if(!hasField(k))continue;
   if(touched.has(k)){if(String(input(k).value)!==String(v))notes.push(config.fields[k].label+'：手入力済みのため、読取候補で上書きしていません。');continue;}
   put(k,v);evidence[k]=result.evidence[k];updateSource(k);
  }
  $('#warnings').replaceChildren(...notes.map(x=>node('p','warn',x)));
  const conflictBox=$('#conflicts');conflictBox.replaceChildren();
  for(const c of result.conflicts){
   if(!hasField(c.key))continue;
   const block=node('div','conflict');
   block.append(node('strong','',config.fields[c.key].label+(c.reason==='remarks_too_long'?'が長いため、原文を残して編集が必要です':'の候補が一致しません')));
   for(const x of c.candidates){
    block.append(node('p','',`${x.value}　［${x.source} / ${x.page}］`));
    if(result.identity_blocked||c.key==='remarks')continue;
    const b=node('button','quiet','この候補を採用');b.addEventListener('click',()=>{
     if(busy)return;
     if(touched.has(c.key)&&String(input(c.key).value)!==String(x.value)&&!confirm('手直し済みの値を、この候補で置き換えますか？'))return;
     put(c.key,x.value,true);evidence[c.key]=x;$('#reviewed').checked=false;updateSource(c.key);block.remove();updateMetrics();
    });block.append(b);
   }
   if(result.identity_blocked)block.append(node('p','','別物件の可能性があります。資料を分けて読み直してください。'));
   if(c.key==='remarks')block.append(node('p','','上の各資料の内容を確認し、備考欄へまとめて入力してください。自動で切り捨てていません。'));
   conflictBox.append(block);
  }
  sources=result.documents||[];$('#sourceSelect').replaceChildren();
  for(const d of sources)for(const p of d.pages){const o=node('option','',d.name+' / '+p.label);o.value=JSON.stringify([d.id,p.page]);$('#sourceSelect').append(o);}
  if(sources.length){$('#sourcePanel').classList.remove('hidden');displaySource();}else{$('#sourcePanel').classList.add('hidden');$('#sourceText').textContent='';}
  updateMetrics();$('#reviewed').checked=false;
  lastReview={warnings:notes};
  if(result.identity_blocked)lastReview.warnings.unshift('物件の識別情報が一致しません。自動候補を外しました。資料を分けて再作成してください。');
  displayReview();await makeReady();
  showNotice($('#draftTitle').textContent);
 }catch(e){if(pendingAI){showNotice('AI処理の結果を確認できません。操作ID：'+pendingAI.id+'。新しいIDで自動再送しません。',true);}if(e.identity_blocked){clearAutoValues();resetRentroll();sources=[];$('#sourcePanel').classList.add('hidden');$('#conflicts').replaceChildren();updateMetrics();}draftFailed(e);toast(e.message);showNotice(e.identity_blocked?'物件を特定できないため、自動値を外しました。資料を分けて読み直してください。':'処理を完了できませんでした。前回の内容を保持しています。今回資料の読取結果ではありません。',true);}finally{setBusy(false);}
}
function displaySource(){if(!$('#sourceSelect').value)return;const [id,page]=JSON.parse($('#sourceSelect').value);const d=sources.find(x=>x.id===id);const p=d?.pages.find(x=>x.page===page);$('#sourceText').textContent=p?.text||'文字を抽出できないページです。元の資料を開いて確認してください。';}
function download(blob,name){const u=URL.createObjectURL(blob),a=node('a');a.href=u;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),30000);}
async function exportFile(){
 if(busy)return;
 if(!loggedIn){toast('認証が必要です。');return;}
 const fields=values();for(const k of config.numeric_fields){if(fields[k]!=null&&(!Number.isFinite(fields[k])||fields[k]<0)){toast(config.fields[k].label+'を確認してください。');return;}}
 setBusy(true,'export');
 try{const r=await call('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fields,as_of:today()})});download(await r.blob(),(fields.property_name||'物件').replace(/[\\/:*?"<>|]/g,'_')+'_物件概要_編集用下書き.xlsx');toast('Excelを出力しました。印刷プレビューを確認してからPDF保存してください。');}
 catch(e){toast(e.message);}finally{setBusy(false);}
}
function saveState(){
 if(busy)return;
 const state={version:'2',fields:values(),manual_fields:[...touched],evidence,feedback,review:lastReview,rentroll:rentSnapshot(),pending_ai:pendingAI,as_of:today()};
 const data=JSON.stringify(state,null,2);if(new Blob([data]).size>8*1024*1024){toast('途中データが8MBを超えるため保存できません。明細を分けて管理してください。');return;}
 download(new Blob([data],{type:'application/json'}),'物件概要_途中データ.json');
 toast('途中データを保存しました。物件情報・引用を含むため、社内の保存先で管理してください。');
}
function validateState(d){
 if(!d||!['1','2'].includes(d.version)||!d.fields||Array.isArray(d.fields)||typeof d.fields!=='object')throw Error();
 for(const [k,v]of Object.entries(d.fields)){
  if(!hasField(k))throw Error();
  if(v!==null&&!['string','number'].includes(typeof v))throw Error();
  if(String(v??'').length>(k==='remarks'?config.remarks_limit:300))throw Error();
  if(config.numeric_fields.includes(k)&&v!==null&&v!==''&&(typeof v!=='number'||!Number.isFinite(v)||v<0||v>=1e13))throw Error();
 }
 if(d.fields.transaction&&!['媒介','代理','売主'].includes(d.fields.transaction))throw Error();
 if(d.version==='2'&&(!Array.isArray(d.manual_fields)||d.manual_fields.some(k=>typeof k!=='string'||!hasField(k))))throw Error();
 if(d.evidence!=null&&(typeof d.evidence!=='object'||Array.isArray(d.evidence)))throw Error();
 for(const [k,e]of Object.entries(d.evidence||{})){
  if(!hasField(k)||!e||typeof e!=='object'||typeof e.quote!=='string'||e.quote.length>16000)throw Error();
  if(e.components&&(!Array.isArray(e.components)||e.components.some(x=>!x||typeof x.quote!=='string'||x.quote.length>16000)))throw Error();
 }
 if(d.pending_ai!=null&&(!d.pending_ai.id||typeof d.pending_ai.id!=='string'||!/^[-a-f0-9]{36}$/.test(d.pending_ai.id)))throw Error();
 if(d.feedback!=null&&(!Array.isArray(d.feedback)||d.feedback.length>200||d.feedback.some(x=>!x||typeof x.text!=='string'||typeof x.status!=='string'||x.text.length>2000||x.status.length>8000)))throw Error();
 if(d.review!=null&&(!Array.isArray(d.review.warnings)||d.review.warnings.length>500||d.review.warnings.some(x=>typeof x!=='string'||x.length>5000)))throw Error();
 validateRentSnapshot(d.rentroll);
 return d;
}
async function loadState(file){
 if(busy){toast('処理完了後に途中データを読み込んでください。');return;}
 if(!file||file.size>8*1024*1024){toast('途中データのサイズを確認してください。');return;}
 const revision=caseRevision;
 try{const d=validateState(JSON.parse(await file.text()));
  if(busy||revision!==caseRevision){toast('画面が変更されたため復元を止めました。');return;}
  reset(false);
  const manual=d.version==='2'?new Set(d.manual_fields):new Set(Object.keys(d.fields).filter(k=>d.fields[k]!==null&&d.fields[k]!==''));
  for(const [k,v]of Object.entries(d.fields))if(k!=='handover')put(k,v,manual.has(k));
  pendingAI=d.pending_ai||pendingAI;if(pendingAI)try{sessionStorage.setItem('shimizu-pending-ai-operation',JSON.stringify(pendingAI));}catch{}evidence=d.evidence||{};restoreRentSnapshot(d.rentroll);
  for(const k of Object.keys(config.fields))updateSource(k);
  $('#reviewed').checked=false;updateMetrics();
  feedback=d.feedback||[];lastReview=d.review||{warnings:[]};displayReview();await makeReady();
  toast('途中データと引用を復元しました。元資料そのものは含まれません。必要な資料だけ再添付してください。');
 }catch{toast('途中データの形式が異なります。現在の内容は変更していません。');}
}
function reset(ask=true){if(busy)return;caseRevision++;if(ask&&!confirm('画面の物件データを消して新しい物件を始めます。必要な途中データは保存済みですか？'))return;clearDelivery();files=[];evidence={};sources=[];touched=new Set();resetRentroll();$('#memo').value='';$('#files').value='';$('#warnings').replaceChildren();$('#conflicts').replaceChildren();$('#sourcePanel').classList.add('hidden');$('#sourceText').textContent='';$('#reviewed').checked=false;renderFiles();buildForm();showNotice('新しい物件です。別物件の内容は引き継いでいません。');}
async function checkSession(){try{await call('/api/session');loggedIn=true;$('#auth').classList.add('hidden');return true;}catch{loggedIn=false;$('#auth').classList.remove('hidden');return false;}}
async function initialize(){
 try{config=await (await fetch('/api/config')).json();buildForm();
 $('#envTag').textContent=config.local?'ローカル試作':'社内限定';$('#aiNote').textContent=config.ai_ready?'承認済みAPIを使用します。資料の送信先を確認してください。':config.ai_note;$('#useAI').disabled=!config.ai_ready;
 if(config.local){loggedIn=await checkSession();showNotice('ローカル試作：AI未接続の場合、定型テキストの読取とExcel出力を試せます。',true);}
 else if(!config.auth_ready){$('#auth').classList.remove('hidden');$('#authNote').textContent='会社用の認証設定が未完了です。管理者の設定が完了するまで、資料の送信・Excel出力は停止しています。';showNotice('本番接続の設定待ちです。無認証で資料は処理しません。',true);}
 else if(config.auth_mode==='iap'){await checkSession();}
 else{const script=node('script');script.src='https://accounts.google.com/gsi/client';script.onload=()=>{
   google.accounts.id.initialize({client_id:config.google_client_id,callback:async r=>{token=r.credential;await checkSession();}});
   google.accounts.id.renderButton($('#googleButton'),{theme:'outline',size:'large',text:'signin_with'});
  };script.onerror=()=>toast('Googleログインを読み込めませんでした。ネットワーク設定を確認してください。');document.head.append(script);$('#auth').classList.remove('hidden');}
 }catch{showNotice('アプリの接続を確認できません。サーバーを起動してからこの画面を開いてください。',true);}
}
$('#saveFeedback').addEventListener('click',saveState);
$('#files').addEventListener('change',e=>addFiles(e.target.files));
const drop=$('#dropzone');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('drag');}));['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('drag');}));drop.addEventListener('drop',e=>addFiles(e.dataTransfer.files));drop.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#files').click();}});
$('#memo').addEventListener('input',()=>{if(lastReview){discardDraft();lastReview=null;$('#feedbackForm').hidden=true;$('#reviewArea').hidden=true;$('#draftTitle').textContent='メモを変更しました';draftInfo('「テキスト・資料から再作成」でExcelに反映します。');}});
$('#extract').addEventListener('click',extract);$('#export').addEventListener('click',exportFile);$('#newCase').addEventListener('click',()=>reset());$('#saveState').addEventListener('click',saveState);$('#loadState').addEventListener('click',()=>$('#stateFile').click());$('#stateFile').addEventListener('change',e=>loadState(e.target.files[0]));$('#sourceSelect').addEventListener('change',displaySource);$('#retryAuth').addEventListener('click',checkSession);
$('#sample').addEventListener('click',()=>{if(busy)return;$('#memo').value='物件名：テスト用レジデンス（架空）\n住居表示：東京都内・架空住所\n地番：架空町1番\n土地権利：所有権\n地目：宅地\n土地面積：200.50㎡\n建物種類：共同住宅\n構造：鉄筋コンクリート造3階建\n延床面積：350.25㎡\n築年月：2005-03\n総戸数：6戸\n間取り：1K×6戸\n現況年間収入：360万円\n満室年間収入：432万円\n用途地域：第一種住居地域\n建ぺい率：60%\n容積率：200%\n備考：この入力は操作確認用の架空データです。';toast('架空のサンプルです。「資料を読み取る」で入力欄へ反映します。');});
$('#previewView').addEventListener('click',()=>{$('#formSections').classList.add('hidden');$('#preview').classList.remove('hidden');$('#previewView').classList.add('selected');$('#editView').classList.remove('selected');});$('#editView').addEventListener('click',()=>{$('#formSections').classList.remove('hidden');$('#preview').classList.add('hidden');$('#editView').classList.add('selected');$('#previewView').classList.remove('selected');});
window.addEventListener('beforeunload',e=>{if(touched.size||sources.length||files.length||$('#memo').value||busy){e.preventDefault();e.returnValue='';}});
initialize();

$('#aiOperationStatus').addEventListener('click',async()=>{
 if(busy)return;if(!pendingAI){toast('確認待ちのAI操作はありません。');return;}
 try{const r=await(await call('/api/operations/'+pendingAI.id)).json();
  const message=`AI処理：${r.status}／初回API枠 ${r.limit_yen}円／換算使用額 ${r.used_yen}円／未精算予約 ${r.reserved_yen}円`;
  showNotice(message,true);
  if(r.status==='settled'&&!r.blocked&&confirm(message+'。前回は送信・精算済みです。新たな費用を伴う読取を許可し、操作IDを更新しますか？')){pendingAI=null;try{sessionStorage.removeItem('shimizu-pending-ai-operation');}catch{}toast('次の読取は新しいAI処理として実行します。');}
 }catch(e){toast(e.message);}
});
