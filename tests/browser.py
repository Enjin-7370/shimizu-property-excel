import json,mimetypes,os
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests/results';OUT.mkdir(exist_ok=True)
runtime=ROOT.parent/'static-runtime/node_modules/pyodide'
LIVE_URL=os.environ.get('SHIMIZU_APP_URL','')
with sync_playwright() as p:
    launch={}
    if LIVE_URL and os.environ.get('HTTPS_PROXY'):
        proxy=urlparse(os.environ['HTTPS_PROXY'])
        launch['proxy']={'server':proxy.scheme+'://'+proxy.hostname+(':'+str(proxy.port) if proxy.port else '')}
        if proxy.username:launch['proxy']['username']=proxy.username
        if proxy.password:launch['proxy']['password']=proxy.password
    b=p.chromium.launch(executable_path=str(ROOT.parent/'browser-bin/chromium'),headless=True,args=['--no-sandbox'],**launch)
    context=b.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
    def route(r):
        path=urlparse(r.request.url).path.split('/')[-1]
        file=runtime/path
        if file.is_file():r.fulfill(body=file.read_bytes(),content_type='application/wasm' if path.endswith('.wasm') else mimetypes.guess_type(path)[0] or 'application/octet-stream',headers={'Access-Control-Allow-Origin':'*'})
        else:r.continue_()
    if not LIVE_URL:context.route('https://cdn.jsdelivr.net/**',route)
    def app_route(r):
        path=urlparse(r.request.url).path.lstrip('/') or 'index.html'
        file=ROOT/'docs'/path
        if file.is_file():r.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(path)[0] or 'application/octet-stream')
        else:r.fulfill(status=404,body='Not found')
    if not LIVE_URL:context.route('http://127.0.0.1:7070/**',app_route)
    if LIVE_URL and os.environ.get('SHIMIZU_TEST_TLS_TRANSPORT')=='1':
        # urllib uses the supplied managed CA and inherited proxy. TLS verification
        # remains on. Every asset is fetched from its actual public HTTPS origin.
        def trusted_transport(r):
            url=r.request.url
            if r.request.method!='GET' or not (url.startswith(LIVE_URL) or url.startswith('https://cdn.jsdelivr.net/pyodide/v0.29.3/full/')):
                r.abort();return
            with urllib.request.urlopen(url,timeout=60) as response:
                r.fulfill(status=response.status,body=response.read(),headers={k:v for k,v in response.headers.items() if k.lower() not in ['content-length','transfer-encoding','connection']})
        context.route('**/*',trusted_transport)
    page=context.new_page();errors=[];requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    context.on('request',lambda r:requests.append({'url':r.url,'method':r.method,'body':r.post_data}))
    page.goto(LIVE_URL or 'http://127.0.0.1:7070',timeout=60000)
    assert page.locator('#entryGate').is_visible()
    assert not page.locator('#workspaceApp').is_visible()
    page.locator('#entryPassword').fill('incorrect-password');page.locator('#entrySubmit').click()
    page.wait_for_function("document.querySelector('#entryMessage').textContent.includes('違います')")
    assert not page.locator('#workspaceApp').is_visible()
    assert not any('application.zip' in r['url'] or 'pyodide' in r['url'] for r in requests)
    page.locator('#entryPassword').fill(os.environ['SHIMIZU_ENTRY_PASSWORD']);page.locator('#entrySubmit').click()
    page.wait_for_selector('#field-property_name')
    page.locator('#sample').click();page.locator('#extract').click()
    page.wait_for_function("!busy",timeout=180000)
    print('NOTICE',page.locator('#notice').inner_text(),'TOAST',page.locator('#toast').inner_text(),flush=True)
    assert page.locator('#field-current_annual_income_yen').input_value()=='3600000'
    assert page.locator('#field-price_yen').input_value()==''
    page.locator('#field-price_yen').fill('60000000')
    assert page.locator('#yieldMetric').inner_text()=='6.00%'
    page.locator('#field-property_name').fill('架空・ブラウザ版確認')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=90000)
    assert page.locator('#field-property_name').input_value()=='架空・ブラウザ版確認'
    with page.expect_download(timeout=90000) as dl:page.locator('#export').click()
    dl.value.save_as(str(OUT/'browser_output.xlsx'))
    with page.expect_download() as dl:page.locator('#saveState').click()
    dl.value.save_as(str(OUT/'state.json'))
    page.on('dialog',lambda d:d.accept())
    page.locator('#newCase').click()
    assert page.locator('#field-property_name').input_value()==''
    page.locator('#stateFile').set_input_files(str(OUT/'state.json'))
    page.wait_for_function("input('property_name').value==='架空・ブラウザ版確認'")
    page.locator('#previewView').click()
    assert '架空・ブラウザ版確認' in page.locator('#preview').inner_text()
    page.screenshot(path=str(OUT/'desktop.png'))
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'mobile.png'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':1440,'height':1000});page.locator('#editView').click()
    page.locator('#newCase').click()
    page.locator('#memo').fill('物件名：再読込検査\n土地面積：100㎡')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=180000)
    assert page.locator('#field-land_area_m2').input_value()=='100'
    page.locator('#memo').fill('物件名：再読込検査')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=90000)
    assert page.locator('#field-land_area_m2').input_value()==''
    page.locator('#newCase').click()
    page.locator('#files').set_input_files(str(OUT/'browser_output.xlsx'))
    page.locator('#fileList select').select_option('notes')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=180000)
    assert page.locator('#sourceSelect option').count()>0
    page.locator('#newCase').click()
    csv=OUT/'rent.csv';csv.write_text('部屋,現況賃料,満室賃料\n101,60000,65000\n102,0,65000\n',encoding='utf-8')
    page.locator('#files').set_input_files(str(csv));page.locator('#fileList select').select_option('rentroll')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=180000)
    assert page.locator('#rentrollPanel').is_visible()
    page.locator('#rentPeriod').select_option('monthly');page.locator('#rentTax').select_option('exempt');page.locator('#rentDate').fill('2026-11-10')
    for k,v in [('unit','1'),('current_rent','2'),('full_rent','3')]:page.locator('[data-rent-mapping="'+k+'"]').select_option(v)
    page.locator('#rentPrepare').click();page.locator('#rentCoverage').check();page.locator('#rentCalculate').click()
    page.wait_for_function('rentResult!==null',timeout=90000)
    assert page.evaluate('rentResult.totals.current_annual_income_yen')=='720000'
    assert page.evaluate('rentResult.totals.full_annual_income_yen')=='1560000'
    page.locator('#rentApply').click()
    assert page.locator('#field-current_annual_income_yen').input_value()=='720000'
    page.locator('#newCase').click()
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    pdf=OUT/'fictional.pdf';c=canvas.Canvas(str(pdf));c.setFont('HeiseiKakuGo-W5',12);c.drawString(70,760,'物件名：架空PDF検査物件');c.drawString(70,730,'土地面積：234㎡');c.save()
    page.locator('#files').set_input_files(str(pdf));page.locator('#fileList select').select_option('notes')
    page.locator('#extract').click();page.wait_for_function('!busy',timeout=180000)
    assert page.locator('#field-property_name').input_value()=='架空PDF検査物件'
    assert page.locator('#field-land_area_m2').input_value()=='234'
    assert not errors,errors
    assert all(r['method']=='GET' and r['body'] is None for r in requests),requests
    result={'passed':True,'environment':LIVE_URL or 'local-static','checks':['entry locked initially','incorrect password refused','engine not loaded before unlock','correct password unlock','text extraction','price stays manual','yield','manual correction retained','xlsx download','state save','reset','state restore','preview','mobile width','stale automatic cleared','xlsx intake','csv rentroll intake','rentroll current 720000','rentroll full 1560000','rentroll apply','PDF Japanese text extraction','PDF numeric extraction','no script errors','no outbound upload'],'requests':requests}
    (OUT/('live_results.json' if LIVE_URL else 'browser_results.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'passed':True,'checks':len(result['checks'])}))
    b.close()
