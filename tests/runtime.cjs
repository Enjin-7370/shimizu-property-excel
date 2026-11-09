const fs=require('fs'),assert=require('assert'),path=require('path');
const root=path.resolve(__dirname,'..');process.chdir(root);
const {loadPyodide}=require(fs.existsSync(path.join(root,'node_modules/pyodide'))?'../node_modules/pyodide':'../../static-runtime/node_modules/pyodide');
(async()=>{
const p=await loadPyodide();await p.loadPackage('pillow');
p.unpackArchive(new Uint8Array(fs.readFileSync('docs/application.zip')),'zip',{extractDir:'/app'});
p.runPython("import sys;sys.path.insert(0,'/app');from browser_backend import dispatch");
function call(r){p.globals.set('_r',JSON.stringify(r));const o=JSON.parse(p.runPython('dispatch(_r)'));assert(o.ok,o.error);return o.data;}
const r=call({action:'extract',text:'物件名：検査用架空物件\n土地面積：120㎡\n現況年間収入：360万円',files:[]});
assert.equal(r.fields.land_area_m2,120);assert.equal(r.fields.current_annual_income_yen,3600000);
const x=call({action:'export',payload:{fields:{...r.fields,price_yen:60000000,transaction:'媒介'},as_of:'2026-11-10'}});
fs.writeFileSync('tests/runtime_output.xlsx',Buffer.from(x.xlsx,'base64'));
assert.equal(p.runPython("import glob;len(glob.glob('/tmp/tmp*'))"),0);
console.log(JSON.stringify({extraction:true,export:true,temporary_files_cleaned:true,python:p.runPython('sys.version'),size:Buffer.from(x.xlsx,'base64').length}));
})();
