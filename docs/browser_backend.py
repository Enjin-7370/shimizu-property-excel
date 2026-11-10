"""Browser-only bridge for the verified template writer and bounded readers."""
import json, base64, tempfile
from pathlib import Path
from extraction import read_document, extract_labels, resolve, ReadError, TYPES
from rentroll import tables, calculate
from draft import inputs, select_sheets, roll_candidates, scan_images, norm
import re
from excel_writer import write_draft

BASE = Path('/app')
SPEC = json.loads((BASE/'data/field_map.json').read_text())

def finish(docs, warnings):
    candidates = []
    for doc in docs:
        for page in doc['pages']:
            if page.get('ocr'):
                # Japanese OCR sometimes inserts spaces inside labels.
                page['text'] = re.sub(r'(?<=[ぁ-鿿]) +(?=[ぁ-鿿])', '', norm(page['text']))
        text = ''.join(p['text'] for p in doc['pages']).replace(' ', '')
        if doc['kind'] == 'land' and re.search('駐車場.{0,8}契約|コインパーキング', text) and '表題部' not in text:
            doc['kind'] = 'unknown'
            doc['warnings'].append('地番・土地面積：土地謄本指定の資料に駐車場契約の記載があります。登記事項の証拠には採用していません。')
        select_sheets(doc)
        candidates.extend(extract_labels(doc))
        candidates.extend(roll_candidates(doc))
        unread = [str(p['page']) for p in doc['pages'] if p.get('visual_required') and not p['text'].strip()]
        if unread:
            doc['warnings'].append(doc['name']+'：'+', '.join(unread)+'頁は文字を確定できません。原本を確認してください。')
        warnings.extend(doc['warnings'])
    fields, evidence, conflicts, notes = resolve(candidates)
    return dict(identity_blocked=any(c['key'] in ('property_name','address') for c in conflicts),
                fields=fields, evidence=evidence, conflicts=conflicts, warnings=list(dict.fromkeys(warnings+notes)),
                rentroll_tables=[t for d in docs for t in tables(d)],
                documents=[{k:v for k,v in d.items() if k!='sheets' and not k.startswith('_')} for d in docs],
                ai_used=False, usage=None, operation_id=None)


pending_scan = None


def handle(request):
    global pending_scan
    action = request['action']
    if action == 'extract':
        pending_scan = None
        items = request.get('files', [])
        text = request.get('text', '').strip()
        warnings, docs, jobs = [], [], []
        for index, (name, raw, kind) in enumerate(inputs(items, warnings)):
            try:
                doc = read_document(name, raw, kind, index)
            except ReadError as exc:
                warnings.append(name+'：'+str(exc))
                continue
            doc['warnings'] = [w for w in doc['warnings'] if not ('AI画像読取' in w or 'AI接続後' in w)]
            docs.append(doc)
            jobs.extend(scan_images(doc, raw, 8-len(jobs)))
        if text:
            docs.append(read_document('入力メモ.txt', text.encode(), 'notes', 100))
        if not docs:
            raise ReadError('読める入力資料がありません。'+' '.join(warnings))
        if sum(len(p['text']) for d in docs for p in d['pages'])>200000:
            raise ReadError('資料の文字量が20万文字を超えました。物件ごとに分けてください。')
        if jobs:
            pending_scan = (docs,warnings)
            return {'scan_jobs':jobs}
        return finish(docs, warnings)
    if action == 'finish_scan':
        if pending_scan is None:
            raise ReadError('対象の資料が切り替わりました。もう一度追加してください。')
        docs, warnings = pending_scan
        pending_scan = None
        for read in request['readings']:
            for d in docs:
                if d['id']!=read['id']:
                    continue
                for page in d['pages']:
                    if page['page']==read['page']:
                        page['text']=read['text'][:15000]
                        page['ocr']=True
                        page['label']+='（文字認識）'
        if request.get('warning'):
            warnings.append(request['warning'])
        return finish(docs, warnings)
    if action == 'calculate':
        return calculate(request['payload'])
    if action == 'export':
        payload=request['payload']
        fields={**payload['fields'],'handover':'相談'}
        if fields.get('transaction') not in (None,'','媒介','代理','売主'):
            raise ReadError('取引形態は媒介・代理・売主から選択してください。')
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'output.xlsx'
            write_draft({'fields':fields,'as_of':payload.get('as_of')},target,BASE/'data/property_overview.xlsx',SPEC)
            return {'xlsx':base64.b64encode(target.read_bytes()).decode()}
    raise ReadError('対応していない操作です。')

def dispatch(raw):
    try:
        return json.dumps({'ok':True,'data':handle(json.loads(raw))},ensure_ascii=False)
    except Exception as exc:
        return json.dumps({'ok':False,'error':str(exc)[:500]},ensure_ascii=False)
