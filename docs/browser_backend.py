"""Browser-only bridge for the verified template writer and bounded readers."""
import json, base64, tempfile
from pathlib import Path
from extraction import read_document, extract_labels, resolve, ReadError, TYPES
from rentroll import tables, calculate
from excel_writer import write_draft

BASE = Path('/app')
SPEC = json.loads((BASE/'data/field_map.json').read_text())

def handle(request):
    action = request['action']
    if action == 'extract':
        items = request.get('files', [])
        text = request.get('text', '').strip()
        if len(items)>10 or sum(len(x['raw_b64'])*3//4 for x in items)>25*1024*1024+30:
            raise ReadError('資料は最大10点・合計25MBまでです。')
        docs=[]; candidates=[]; warnings=[]
        for i,item in enumerate(items):
            docs.append(read_document(item['name'],base64.b64decode(item['raw_b64'],validate=True),item['kind'],i))
        if text:
            docs.append(read_document('入力メモ.txt',text.encode(),'notes',len(docs)))
        if not docs: raise ReadError('資料かテキストを追加してください。')
        if sum(len(p['text']) for d in docs for p in d['pages'])>200000:
            raise ReadError('資料の文字量が20万文字を超えました。物件ごとに分けてください。')
        for doc in docs:
            candidates.extend(extract_labels(doc)); warnings.extend(doc['warnings'])
        fields,evidence,conflicts,notes=resolve(candidates)
        warnings.extend(notes)
        return dict(identity_blocked=any(c['key'] in ('property_name','address') for c in conflicts),
                    fields=fields,evidence=evidence,conflicts=conflicts,warnings=list(dict.fromkeys(warnings)),
                    rentroll_tables=[t for d in docs for t in tables(d)],
                    documents=[{k:v for k,v in d.items() if k!='sheets' and not k.startswith('_')} for d in docs],
                    ai_used=False,usage=None,operation_id=None,note='候補です。原資料と照合してからExcel出力してください。')
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
