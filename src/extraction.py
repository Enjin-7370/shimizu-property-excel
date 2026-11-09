"""Bounded document readers and conservative, evidence-linked draft extraction.
No outbound calls. Uploaded files are data, never commands.
"""
from __future__ import annotations
import io, json, re, zipfile, unicodedata, hashlib
from pathlib import PurePath
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from PIL import Image
from pypdf import PdfReader

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
TYPES = {
 'notes':'入力メモ', 'map':'住宅地図', 'land':'土地謄本', 'building':'建物謄本',
 'drawing':'建物図面', 'rentroll':'レントロール', 'management':'管理委託契約書',
 'tax':'固定資産税評価証明書', 'repair':'修繕履歴', 'zoning':'用途地域図', 'unknown':'未分類'
}
MANUAL = {'price_yen','transport','road_value_yen_m2','road_direction_width','road_type','transaction'}
SOURCES = {
 'property_name': ['notes','map','land','building','drawing','management','rentroll'],
 'address':['notes','map'], 'parcel_address':['notes','land'],
 'land_right':['notes','land'], 'land_category':['notes','land'], 'land_area_m2':['notes','land'],
 'land_area_basis':['notes','land'], 'building_type':['notes','building','drawing'],
 'structure':['notes','building','drawing'], 'building_area_m2':['notes','building','drawing'],
 'built_date':['notes','building','drawing'], 'units':['notes','drawing','management'],
 'unit_mix':['notes','drawing','management'],
 'full_annual_income_yen':['notes','rentroll'], 'current_annual_income_yen':['notes','rentroll'],
 'zoning_area':['notes','zoning'],'land_use_zone':['notes','zoning'],
 'building_coverage_pct':['notes','zoning'],'floor_area_ratio_pct':['notes','zoning'],
 'fire_zone':['notes','zoning'],'height_district':['notes','zoning'],
 'min_site_area':['notes','zoning'],'absolute_height':['notes','zoning'],
 'other_restrictions':['notes','zoning'],
 'remarks':['notes','management','tax','repair','rentroll']
}
ALIASES = {
 'property_name':['物件名','物件名称'], 'address':['住居表示'], 'parcel_address':['地番','所在（地番）'],
 'land_area_basis':['面積基準'], 'land_right':['土地権利','権利'], 'land_category':['地目'], 'land_area_m2':['土地面積','地積'],
 'building_type':['建物種類','建物の種類'], 'structure':['構造','建物構造'],
 'building_area_m2':['床面積','延床面積','延べ床面積','建物面積'], 'built_date':['築年月日','築年月','新築年月日'],
 'units':['総戸数'], 'unit_mix':['間取り','間取'],
 'full_annual_income_yen':['満室年間収益','満室年間収入','満室想定年間収入'],
 'current_annual_income_yen':['現況年間収益','現況年間収入','現状年間収入'],
 'zoning_area':['区域区分'], 'land_use_zone':['用途地域'],
 'building_coverage_pct':['建ぺい率','建蔽率'], 'floor_area_ratio_pct':['容積率'],
 'fire_zone':['防火地域'], 'height_district':['高度地区'],
 'min_site_area':['敷地規模の最低限度','敷地面積の最低限度'],
 'absolute_height':['絶対高さ'], 'other_restrictions':['その他制限'], 'remarks':['備考']
}
NUMERIC = {'land_area_m2','building_area_m2','building_coverage_pct','floor_area_ratio_pct',
 'full_annual_income_yen','current_annual_income_yen'}

class ReadError(ValueError): pass
class IdentityMismatch(ReadError): pass

def plain(si):
    # Phonetic annotations are not part of a cell value.
    return ''.join(t.text or '' for ch in si for t in ([ch] if ch.tag==NS+'t' else ch.iter(NS+'t')) if ch.tag!=NS+'rPh')

def numeric(raw):
    s=unicodedata.normalize('NFKC',str(raw)).replace(',','').replace(' ','').replace('￥','').replace('¥','')
    m=re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(億|万)?(?:円|m2|m²|㎡|%|平方メートル)?',s)
    if not m: return None
    v=float(m.group(1))*{'億':100000000,'万':10000,None:1}[m.group(2)]
    return v if v < 1e13 else None


def numeric_for_key(raw, key):
    """Reject mismatched units instead of turning e.g. 円 into square metres."""
    text = unicodedata.normalize('NFKC', str(raw)).strip()
    if key.endswith('_m2') and any(x in text for x in ('円','万','億','%','¥','￥')):
        return None
    if key.endswith('_yen') and any(x in text for x in ('m2','m²','平方メートル','%')):
        return None
    if key.endswith('_pct') and any(x in text for x in ('円','万','億','m2','m²','平方メートル')):
        return None
    return numeric(raw)

def read_xlsx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist())!=len(set(z.namelist())):raise ReadError('Excel内部に重複した部品があります。通常のExcelで保存し直してください。')
        if len(z.infolist())>1500 or sum(i.file_size for i in z.infolist())>35_000_000:
            raise ReadError('Excelの展開容量が大きすぎます。対象シートだけに分けてください。')
        if any('vbaproject' in n.lower() or 'externallinks/' in n.lower() for n in z.namelist()):
            raise ReadError('マクロ・外部参照を含むExcelは受付できません。値だけのコピーを使用してください。')
        strings=[]
        if 'xl/sharedStrings.xml' in z.namelist(): strings=[plain(si) for si in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        wb=ET.fromstring(z.read('xl/workbook.xml'))
        rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in rels}
        pages=[]; sheets=[]
        for index,s in enumerate(wb.find(NS+'sheets')):
            target=targets.get(s.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'),'')
            path=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            if '..' in path.split('/'): raise ReadError('Excel内部参照が不正です。')
            if path not in z.namelist(): continue
            root=ET.fromstring(z.read(path)); grid=[]; lines=[]
            rows=root.findall('.//'+NS+'sheetData/'+NS+'row')
            if len(rows)>1200: raise ReadError('Excelは1シート1,200行までです。対象範囲だけに分けてください。')
            for row in rows:
                cells={}
                for c in row:
                    a=c.get('r',''); v=c.find(NS+'v'); typ=c.get('t'); value=v.text if v is not None else ''
                    if typ=='s': value=strings[int(value)] if value else ''
                    elif typ=='inlineStr': value=plain(c.find(NS+'is')) if c.find(NS+'is') is not None else ''
                    elif typ=='e': value=''  # Error caches are not facts or numeric zero.
                    if value not in (None,''):
                        cells[a]=value
                if cells:
                    grid.append(cells); lines.append(' | '.join(f'{a}={v}' for a,v in cells.items()))
            text='\n'.join(lines)
            if len(text)>100000: raise ReadError('Excelの文字量が大きすぎます。')
            props=wb.find(NS+'workbookPr')
            epoch1904=props is not None and props.get('date1904') in ('1','true')
            pages.append({'page':index+1,'label':s.get('name',''),'text':text,'epoch1904':epoch1904})
            sheets.append({'name':s.get('name',''),'rows':grid})
        return pages,sheets

def _read_document(name,raw,kind='unknown',index=0):
    if kind not in TYPES: raise ReadError('資料種別を選び直してください。')
    name=PurePath(name.replace('\\','/')).name[:120]
    if not name or len(raw)>8*1024*1024: raise ReadError('ファイルは1点8MB以下にしてください。')
    ext=PurePath(name).suffix.lower()
    doc={'id':f'doc-{index+1}','name':name,'kind':kind,'pages':[],'warnings':[],'sheets':[], 'visual':False, 'sha256':hashlib.sha256(raw).hexdigest()}
    if ext in ('.txt','.md','.csv'):
        for enc in ('utf-8-sig','cp932'):
            try: text=raw.decode(enc); break
            except UnicodeDecodeError: continue
        else: raise ReadError('文字コードを読み取れません。UTF-8のテキストにしてください。')
        if len(text)>100000: raise ReadError('テキストは10万文字以内です。')
        doc['pages']=[{'page':1,'label':'テキスト','text':text}]
    elif ext=='.xlsx':
        doc['pages'],doc['sheets']=read_xlsx(raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if any(n.startswith('xl/media/') for n in z.namelist()):doc['warnings'].append('Excel内の画像・図形は自動読取の対象外です。図面・地図は画像またはPDFとして追加してください。')
            if any(b'<f' in z.read(n) or b':f>' in z.read(n) for n in z.namelist() if n.startswith('xl/worksheets/') and n.endswith('.xml')):doc['warnings'].append('Excelの数式セルは保存時の値を参照します。再計算後の最新ファイルか確認してください。')
    elif ext=='.pdf':
        if not raw.startswith(b'%PDF'): raise ReadError('PDFの実体を確認できません。')
        r=PdfReader(io.BytesIO(raw),strict=False)
        if r.is_encrypted: raise ReadError('パスワード付きPDFは受付できません。解除済みの資料を使用してください。')
        if len(r.pages)>25: raise ReadError('PDFは25ページ以内に分けてください。')
        doc['pages']=[{'page':i+1,'label':f'{i+1}ページ','text':p.extract_text() or ''} for i,p in enumerate(r.pages)]
        # Maps, drawings and zoning charts retain meaning in graphics even with a text layer.
        if kind in ('map','drawing','zoning'):
            doc['visual']=True
            for page in doc['pages']:page['visual_required']=True
        for page in doc['pages']:
            if len(page['text'].strip())<30:page['visual_required']=True
        if any(len(p['text'].strip())<30 for p in doc['pages']):
            doc['visual']=True;doc['warnings'].append('画像中心のページがあります。AI画像読取または原本を見ながらの手入力が必要です。')
        if sum(len(p['text']) for p in doc['pages'])>150000: raise ReadError('PDFの文字量が上限を超えました。')
    elif ext in ('.png','.jpg','.jpeg','.webp'):
        with Image.open(io.BytesIO(raw)) as im:
            if im.width*im.height>25_000_000: raise ReadError('画像は2,500万画素以下にしてください。')
            im.verify()
        doc['visual']=True
        doc['pages']=[{'page':1,'label':'画像','text':'','visual_required':True}]
        doc['warnings'].append('画像読取はAI接続後に利用できます。現在は原本確認・手入力でも進められます。')
    else: raise ReadError('対応形式はPDF、PNG/JPEG/WebP、XLSX、TXT/MD/CSVです。ZIPや実行ファイルは受付しません。')
    alltext='\n'.join(p['text'] for p in doc['pages'])
    if kind=='land' and re.search('駐車場使用契約書|コインパーキング用',alltext) and '表題部' not in alltext:
        doc['warnings'].append('「土地謄本」の指定ですが駐車場契約書の可能性があります。資料種別と原本を確認してください。')
        doc['kind']='unknown'
    return doc


def read_document(name, raw, kind='unknown', index=0):
    try:
        return _read_document(name, raw, kind, index)
    except ReadError:
        raise
    except Exception:
        raise ReadError('資料を読み取れません。破損・暗号化・拡張子と実体を確認し、開けるPDF・画像・Excelにして再選択してください。') from None

def candidate(key,val,doc,page,quote,method='label'):
    return {'key':key,'value':val,'source':doc['name'],'source_id':doc['id'],'kind':doc['kind'],
            'page':page,'quote':quote[:4000],'method':method,'review_required':True,'source_sha256':doc.get('sha256','')}

def extract_labels(doc):
    result=[]
    for p in doc['pages']:
        for line in p['text'].splitlines():
            line=line.strip()
            for key,names in ALIASES.items():
                if doc['kind'] not in SOURCES.get(key,[]): continue
                for label in sorted(names,key=len,reverse=True):
                    match=re.match(r'^[・\s]*'+re.escape(label)+r'\s*[:：]\s*(.+)$',line)
                    if match:
                        v=match.group(1).strip()
                        if key in NUMERIC:
                            v=numeric_for_key(v,key)
                            if v is None: break
                        if len(str(v))<=(4000 if key=='remarks' else 300): result.append(candidate(key,v,doc,p['page'],line))
                        elif key=='remarks':doc['warnings'].append('長い備考を自動転記していません。原文を確認し、必要部分を手入力してください。')
                        break
    # A known overview is an explicit import, not proof from original registries.
    for p,s in zip(doc['pages'],doc['sheets']):
        vals={a:v for row in s['rows'] for a,v in row.items()}
        if doc['kind']=='notes' and vals.get('A1','').replace(' ','').replace('　','')=='物件概要書':
            import json
            spec=json.loads((__import__('pathlib').Path(__file__).parent/'data/field_map.json').read_text())
            for key,info in spec['fields'].items():
                if key in MANUAL or key in ('handover','agent') or key.startswith('company_'):continue
                v=vals.get(info['cell'])
                if not v: continue
                if key in NUMERIC:
                    v=numeric_for_key(v,key)
                    if v is None:continue
                if key=='built_date' and re.fullmatch(r'[0-9]+(?:\.0)?',str(v)):
                    try:v=((date(1904,1,1) if p.get('epoch1904') else date(1899,12,30))+timedelta(days=float(v))).isoformat()
                    except (ValueError,OverflowError):continue
                result.append(candidate(key,v,doc,p['page'],f"{info['cell']}={vals[info['cell']]}",'overview-import'))
    return result

def resolve(candidates):
    by={}; conflicts=[]; fields={}; evidence={}; warnings=[]
    for c in candidates:
        if c['key'] in MANUAL or c['key'] not in SOURCES:continue
        if c.get('kind') not in SOURCES[c['key']]:continue
        by.setdefault(c['key'],[]).append(c)
    for key,cs in by.items():
        # Repeating the same quote or file must not double the notes.
        unique=[]; seen=set()
        for c in cs:
            value=str(c['value']).strip()
            if value in seen:continue
            seen.add(value);unique.append(c)
        if key=='remarks':
            combined='\n'.join(str(c['value']).strip() for c in unique)
            if len(combined)>420:
                conflicts.append({'key':key,'candidates':unique,'reason':'remarks_too_long'})
                warnings.append('備考候補が420文字を超えています。候補を削らず表示していますので、必要部分を編集してください。')
            else:
                fields[key]=combined
                evidence[key]={**unique[0], 'value':combined, 'method':'combined-remarks', 'components':unique}
        elif len(unique)>1:
            conflicts.append({'key':key,'candidates':unique,'reason':'conflicting_values'})
        else:
            fields[key]=unique[0]['value'];evidence[key]=unique[0]
    # Different addresses are also an identity conflict, even when one document omits the name.
    if any(c['key'] in ('property_name','address') for c in conflicts):
        return {},{},conflicts,['物件名または住居表示が一致しないため、一括反映を停止しました。同じ物件か原本を確認し、資料を整理してください。']
    apply_height_rule(fields,evidence,conflicts,warnings)
    return fields,evidence,conflicts,warnings

def apply_height_rule(fields,evidence,conflicts,warnings):
    # Exact internal template note AH41; not a general statement of planning law.
    height=fields.get('absolute_height')
    if not height:return
    zone=fields.get('land_use_zone','')
    if not zone or any(c['key'] in ('land_use_zone','height_district') for c in conflicts):
        fields.pop('absolute_height',None)
        evidence.pop('absolute_height',None)
        warnings.append('高さ制限の記載先を確定できません。用途地域を確認してから高度地区／絶対高さへ記入してください。')
        return
    if '低層住居専用地域' in zone:return
    old=fields.get('height_district','')
    combined=(old+'／' if old else '')+'高さ制限：'+str(height)
    components=[evidence[k] for k in ('height_district','absolute_height') if k in evidence]
    fields.pop('absolute_height',None);evidence.pop('absolute_height',None)
    if len(combined)>300:
        warnings.append('高さ制限の併記が長すぎます。元資料を確認して高度地区欄を編集してください。');return
    fields['height_district']=combined
    evidence['height_district']={**components[0],'key':'height_district','value':combined,'components':components}
    warnings.append('完成見本の欄外注記に従い、低層以外の高さ制限を高度地区欄へ併記しました。')
