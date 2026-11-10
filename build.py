"""Assemble only public-safe files. Never copy reference/, source docs or credentials."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).parent
SOURCE=ROOT/'src'
OUT=ROOT/'docs'
spec=json.loads((SOURCE/'data/field_map.json').read_text())
spec.pop('authority',None)
with zipfile.ZipFile(OUT/'application.zip','w',zipfile.ZIP_DEFLATED) as z:
    for name in ['excel_writer.py','extraction.py','rentroll.py','draft.py']:
        z.write(SOURCE/name,name)
    z.write(OUT/'browser_backend.py','browser_backend.py')
    z.writestr('data/field_map.json',json.dumps(spec,ensure_ascii=False))
    z.write(SOURCE/'data/property_overview.xlsx','data/property_overview.xlsx')
    with zipfile.ZipFile(ROOT/'vendor/pypdf-5.9.0.zip') as package:
        for name in package.namelist():z.writestr(name,package.read(name))
sha=hashlib.sha256((OUT/'application.zip').read_bytes()).hexdigest()
worker=(OUT/'worker.js').read_text()
worker=re.sub(r'^const APP_SHA=.*?;\n','',worker)
(OUT/'worker.js').write_text('const APP_SHA='+json.dumps(sha)+';\n'+worker)
config=dict(release='0.5.0-browser',local=True,auth_ready=True,auth_mode='browser',ai_ready=False,
    ai_note='画像内の日本語は端末で文字認識します。外部AIは未接続です。',
    fields=spec['fields'],numeric_fields=spec['numeric_fields'],defaults=spec['default_company'],
    manual_only=spec['manual_only'],types={'notes':'入力メモ','map':'住宅地図','land':'土地謄本','building':'建物謄本','drawing':'建物図面','rentroll':'レントロール','management':'管理委託契約書','tax':'固定資産税評価証明書','repair':'修繕履歴','zoning':'用途地域図','unknown':'未分類'},remarks_limit=spec['limits']['remarks_chars'])
(OUT/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2))
js=(SOURCE/'static/app.js').read_text()
js=js[:js.index("$('#aiOperationStatus').addEventListener")]
js=re.sub(r"let pendingAI=null;try\{.*?\}catch\{\}","let pendingAI=null;",js,count=1)
start=js.index('async function call(');end=js.index('\nfunction setBusy',start)
js=js[:start]+"async function call(path,options={}){return BrowserAPI.call(path,options);}\n"+js[end:]
js=js.replace("config=await (await fetch('/api/config')).json()","config=await BrowserAPI.config()")
js=js.replace("config.local?'ローカル試作':'社内限定'","'ブラウザ内処理'")
js=js.replace("if(config.local){loggedIn=await checkSession();showNotice('ローカル試作：AI未接続の場合、定型テキストの読取とExcel出力を試せます。',true);}","if(config.local){loggedIn=await checkSession();showNotice('資料とExcelはこのブラウザ内だけで処理します。AI読取は設定待ちです。');}")
js=js.replace("サーバーを起動してからこの画面を開いてください。","通信を確認して再読み込みしてください。")
js=js.replace("files=[];evidence={};sources=[];touched=new Set();resetRentroll();","BrowserAPI.reset();files=[];evidence={};sources=[];touched=new Set();resetRentroll();")
js=js.replace("AIの抽出候補を反映しました。資料との照合をお願いします。","AIの抽出候補を反映しました。資料との照合をお願いします。")
js=js.replace("PDF保存してください。","印刷・PDF保存してください。")
(OUT/'app.js').write_text(js)
html=(SOURCE/'static/index.html').read_text().replace('/static/','./')
html=html.replace('<head>','<head><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\' https://cdn.jsdelivr.net \'wasm-unsafe-eval\' \'unsafe-eval\'; worker-src \'self\' blob:; connect-src \'self\' https://cdn.jsdelivr.net; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data: blob:; font-src \'self\' data:; object-src \'none\'; base-uri \'self\'; form-action \'none\'"><meta name="referrer" content="no-referrer">')
html=html.replace('<button id="aiOperationStatus" class="link">前回AI処理の状態・費用を確認</button>','')
html=html.replace('<script src="./app.js"','<script src="./browser-api.js" defer></script><script src="./app.js"')
html=re.sub(r'<p class="privacy">.*?</p>','<p class="privacy">資料・入力内容・生成Excelはブラウザ内のメモリで処理し、サーバーへ送信・保存しません。ページを閉じると作業内容は失われます。必要なときだけ「途中データを保存」で端末へ保存できます。初回は読取エンジンのダウンロードに時間がかかります。AIは未接続です。</p>',html)
html=re.sub(r'<script src="\./(?:browser-api|app|rentroll)\.js" defer></script>','',html)
html=html.replace('</head>','<link rel="stylesheet" href="./gate.css"></head>')
gate='''<section class="entry-gate" id="entryGate"><div class="entry-card"><div class="entry-brand">ENJIN ASSET MANAGEMENT</div><h1>物件概要ワークスペース</h1><p>パスワードを入力して、作業を始めてください。</p><form id="entryForm"><label for="entryPassword">パスワード</label><input type="password" id="entryPassword" autocomplete="current-password" required maxlength="64" autofocus><button type="submit" id="entrySubmit">ワークスペースを開く →</button><p id="entryMessage" class="entry-error" role="alert" aria-live="polite"></p></form><p class="entry-foot">資料・Excelはブラウザ内で処理します。</p></div></section>'''
html=html.replace('<body>','<body>'+gate+'<div id="workspaceApp" hidden>')
html=html.replace('</body>','</div><script src="./gate.js" defer></script></body>')
(OUT/'index.html').write_text(html)
(OUT/'.nojekyll').touch()
(OUT/'SHA256SUMS.txt').write_text('\n'.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt')+'\n')
print('Public app built',sha)
