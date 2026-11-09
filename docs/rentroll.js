'use strict';
// Source tables remain local to this case; calculations run in the browser worker.
let rentTables=[], rentRows=[], rentResult=null, rentIdentityBlocked=false;
const rentComponents={rent:'賃料',common:'共益費',parking:'駐車場',other:'その他定期収入',one_time:'一時金'};
function rentSelect(choices,value,label,onchange){const el=node('select');el.setAttribute('aria-label',label);for(const [v,t]of choices){const o=node('option','',t);o.value=v;el.append(o);}el.value=value;el.addEventListener('change',onchange);return el;}
function rentInvalidate(){rentResult=null;$('#rentApply').disabled=true;$('#rentSummary').textContent='明細を確認して集計してください。';}
function resetRentroll(){rentTables=[];rentRows=[];rentIdentityBlocked=false;rentInvalidate();$('#rentrollPanel').classList.add('hidden');$('#rentRows').replaceChildren();}
function acceptRentTables(tables,blocked){resetRentroll();rentIdentityBlocked=blocked;if(blocked||!tables.length)return;rentTables=tables;$('#rentrollPanel').classList.remove('hidden');const select=$('#rentTable');select.replaceChildren();tables.forEach((t,i)=>{const o=node('option','',t.source+' / '+t.label);o.value=String(i);select.append(o);});showRentTable();}
function showRentTable(){
 const t=rentTables[Number($('#rentTable').value)];if(!t)return;
 if(t.review_rows){$('#rentHeader').replaceChildren(node('option','','AI明細候補'));$('#rentMapping').replaceChildren();$('#rentRaw').textContent='AI候補を原資料と照合してください。下のボタンで確認用明細へ取り込みます。期間・税区分・基準日は明細ごとに確認します。';return;}
 const headers=$('#rentHeader');headers.replaceChildren();t.rows.slice(0,30).forEach((r,i)=>{const o=node('option','',`${r.row}行：`+Object.values(r.cells).join(' / ').slice(0,120));o.value=String(i);headers.append(o);});showRentMapping();
}
function showRentMapping(){
 const t=rentTables[Number($('#rentTable').value)],h=t?.rows[Number($('#rentHeader').value)];if(!h)return;
 const mount=$('#rentMapping');mount.replaceChildren();const columns=[...new Set(t.rows.flatMap(r=>Object.keys(r.cells)))].sort((a,b)=>{const n=x=>/^\d+$/.test(x)?Number(x):[...x].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0);return n(a)-n(b);});
 for(const [id,label]of [['unit','部屋・区画'],['current_rent','現況賃料'],['full_rent','満室賃料'],['current_common','現況共益費'],['full_common','満室共益費'],['current_parking','現況駐車場'],['full_parking','満室駐車場']]){
  const field=node('label','',label);const choices=[['','指定なし'],...columns.map(c=>[c,`${c}：${h.cells[c]||'（見出し空欄）'}`])];const select=rentSelect(choices,'',label,()=>{});select.dataset.rentMapping=id;field.append(select);mount.append(field);
 }
 const preview=$('#rentRaw');preview.replaceChildren();for(const r of t.rows.slice(Number($('#rentHeader').value),Number($('#rentHeader').value)+6)){preview.append(node('p','',`${r.row}行：`+Object.entries(r.cells).map(([c,v])=>c+'='+v).join(' / ')));}
}
function prepareRentRows(){
 if(busy)return;const t=rentTables[Number($('#rentTable').value)];if(!t)return;
 if(t.review_rows){if(rentRows.length&&!confirm('現在の明細をAI候補で置き換えますか？'))return;rentRows=JSON.parse(JSON.stringify(t.review_rows));$('#rentCoverage').checked=false;rentInvalidate();renderRentRows();return;}
 const m=Object.fromEntries([...document.querySelectorAll('[data-rent-mapping]')].map(el=>[el.dataset.rentMapping,el.value]));
 if(!m.unit||!['rent','common','parking'].some(c=>m['current_'+c]||m['full_'+c])){toast('部屋・区画と、収入の列を指定してください。');return;}
 const selected=Object.values(m).filter(Boolean);if(new Set(selected).size!==selected.length){toast('同じ列を二つの金額・区画へ割り当てないでください。');return;}
 if(rentRows.length&&!confirm('現在の明細編集を、この表からの読取内容へ置き換えますか？'))return;
 const period=$('#rentPeriod').value,tax=$('#rentTax').value,asof=$('#rentDate').value;const rows=[];
 for(const r of t.rows.slice(Number($('#rentHeader').value)+1)){
  for(const c of ['rent','common','parking']){
   const cur=m['current_'+c],full=m['full_'+c];if(!cur&&!full)continue;
   const a=cur?(r.cells[cur]??''):'',b=full?(r.cells[full]??''):'';if(a===''&&b==='')continue;
   const unit=r.cells[m.unit]||'',total=/合計|小計|総計|subtotal|total/i.test(unit);
   rows.push({id:`${t.document_id}-${t.page}-${r.row}-${c}`,unit,component:c,current_amount:a,full_amount:b,period,tax_basis:tax,as_of:asof,include:!total,exclusion_reason:total?'合計行のため除外':'',source:{document_id:t.document_id,sha256:t.sha256,page:t.page,row:r.row,label:t.label,quote:Object.entries(r.cells).map(([k,v])=>k+'='+v).join(' | ').slice(0,4000)}});
  }
 }
 if(!rows.length){toast('指定した列に明細がありません。見出し行・列を確認してください。');return;}
 if(rows.length>3600){toast('明細が3,600行を超えています。表を分けてください。');return;}
 rentRows=rows;$('#rentCoverage').checked=false;rentInvalidate();renderRentRows();
}
function renderRentRows(){
 const mount=$('#rentRows');mount.replaceChildren();
 rentRows.forEach(r=>{
  const block=node('details','rent-row');block.open=rentRows.length<=12;const summary=node('summary','',`${r.unit||'区画不明'} · ${rentComponents[r.component]||'区分不明'} · ${r.source.label} ${r.source.row}行`);block.append(summary);const refresh=()=>{summary.textContent=`${r.unit||'区画不明'} · ${rentComponents[r.component]||'区分不明'} · ${r.source.label} ${r.source.row}行`;};const grid=node('div','rent-grid');
  function edit(label,key,type='text'){const lab=node('label','',label),el=node('input');el.type=type;el.value=r[key]??'';el.setAttribute('aria-label',label);el.addEventListener('input',()=>{r[key]=el.value;refresh();rentInvalidate();});lab.append(el);grid.append(lab);}
  edit('部屋・区画','unit');edit('現況金額（円）','current_amount');edit('満室金額（円）','full_amount');
  for(const [label,key,choices]of [['収入区分','component',Object.entries(rentComponents)],['期間','period',[['unknown','未確認'],['monthly','月額'],['annual','年額']]],['税区分','tax_basis',[['unknown','未確認'],['inclusive','税込'],['exclusive','税抜'],['exempt','非課税']]]]){const lab=node('label','',label);lab.append(rentSelect(choices,r[key]||'unknown',label,e=>{r[key]=e.target.value;refresh();rentInvalidate();}));grid.append(lab);}
  edit('基準日','as_of','date');const lab=node('label','rent-check','採用する');const check=node('input');check.type='checkbox';check.checked=r.include;check.addEventListener('change',()=>{r.include=check.checked;rentInvalidate();});lab.prepend(check);grid.append(lab);edit('除外理由','exclusion_reason');
  const source=node('pre','',r.source.quote);block.append(grid,source);mount.append(block);
 });
}
async function calculateRentroll(){
 if(busy||!rentRows.length)return;setBusy(true,'rentroll');
 try{rentResult=await(await call('/api/rentroll/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rows:rentRows,coverage_confirmed:$('#rentCoverage').checked})})).json();const t=rentResult.totals;
  $('#rentSummary').textContent=`採用 ${rentResult.included_count}件／除外 ${rentResult.excluded_count}件\n現況年間：${t.current_annual_income_yen===null?'確認待ち':yen(t.current_annual_income_yen)}\n満室年間：${t.full_annual_income_yen===null?'確認待ち':yen(t.full_annual_income_yen)}\n`+[...rentResult.issues,...Object.entries(rentResult.missing).filter(([,v])=>v.length).map(([k,v])=>`${k==='current'?'現況':'満室'}の未入力：${v.length}件（空欄は0と別）`)].join('\n');
  $('#rentApply').disabled=!Object.values(t).some(v=>v!==null)||rentIdentityBlocked;
 }catch(e){rentInvalidate();toast(e.message);}finally{setBusy(false);}
}
function applyRentroll(){
 if(busy||!rentResult||rentIdentityBlocked)return;const pairs=Object.entries(rentResult.totals).filter(([,v])=>v!==null);
 if(pairs.some(([k])=>touched.has(k))&&!confirm('手入力・確定済みの年間収入を、今回の確認済み集計へ置き換えますか？'))return;
 for(const [k,v]of pairs){put(k,v,true);evidence[k]={key:k,value:v,method:'rentroll-reviewed',source:'確認済み明細集計',page:1,quote:`基準日：${rentResult.as_of}\n採用${rentResult.included_count}件／除外${rentResult.excluded_count}件\n年間合計：${v}円`};updateSource(k);}
 $('#reviewed').checked=false;updateMetrics();toast('確認できた年間収入を反映しました。未確定の側は置き換えていません。');
}
function rentSnapshot(){return rentRows.length?{rows:rentRows,coverage_confirmed:$('#rentCoverage').checked}:null;}
function validateRentSnapshot(s){if(s==null)return;if(!s||!Array.isArray(s.rows)||s.rows.length>3600||typeof s.coverage_confirmed!=='boolean')throw Error();for(const r of s.rows){if(!r||typeof r!=='object'||typeof r.include!=='boolean'||!r.source||typeof r.source.quote!=='string'||r.source.quote.length>4000)throw Error();for(const k of ['id','unit','component','period','tax_basis','as_of','exclusion_reason'])if(typeof r[k]!=='string'||r[k].length>300)throw Error();for(const k of ['current_amount','full_amount'])if(r[k]!==null&&(typeof r[k]!=='string'&&typeof r[k]!=='number'||String(r[k]).length>100))throw Error();}}
function restoreRentSnapshot(s){if(!s)return;rentRows=s.rows;$('#rentrollPanel').classList.remove('hidden');$('#rentCoverage').checked=s.coverage_confirmed;rentInvalidate();renderRentRows();}
$('#rentTable').addEventListener('change',showRentTable);$('#rentHeader').addEventListener('change',showRentMapping);$('#rentPrepare').addEventListener('click',prepareRentRows);$('#rentCalculate').addEventListener('click',calculateRentroll);$('#rentApply').addEventListener('click',applyRentroll);$('#rentCoverage').addEventListener('change',rentInvalidate);
