"""Deterministic rent-roll review. No AI, tax conversion, vacancy or annualisation guesses."""
from __future__ import annotations
import csv, io, re
from decimal import Decimal, InvalidOperation
from datetime import date
from extraction import ReadError

COMPONENTS = ('rent', 'common', 'parking', 'other', 'one_time')

def tables(doc):
    """Keep cell addresses and row numbers. A table is a candidate, never a fact."""
    if doc['kind'] != 'rentroll':
        return []
    result=[]
    if doc.get('sheets'):
        for page, sheet in zip(doc['pages'], doc['sheets']):
            rows=[]
            for cells in sheet['rows']:
                row_number=int(re.search(r'\d+$', next(iter(cells))).group())
                rows.append({'row':row_number, 'cells':{re.sub(r'\d+$','',k):str(v) for k,v in cells.items()}})
            result.append({'document_id':doc['id'],'source':doc['name'],'sha256':doc['sha256'],
                           'page':page['page'],'label':sheet['name'],'rows':rows})
    elif doc['name'].lower().endswith(('.csv','.tsv')):
        text=doc['pages'][0]['text']
        delimiter='\t' if doc['name'].lower().endswith('.tsv') else ','
        parsed=list(csv.reader(io.StringIO(text), delimiter=delimiter))
        if len(parsed)>1200 or any(len(r)>100 for r in parsed):
            raise ReadError('レントロールは1表1,200行・100列以内に分けてください。')
        rows=[{'row':i+1,'cells':{str(j+1):v for j,v in enumerate(row)}} for i,row in enumerate(parsed)]
        result.append({'document_id':doc['id'],'source':doc['name'],'sha256':doc['sha256'],
                       'page':1,'label':'CSV','rows':rows})
    if doc.get('_rentroll_review_rows'):
        result.append({'document_id':doc['id'],'source':doc['name'],'sha256':doc['sha256'],'page':1,'label':'AI明細候補（要原本照合）','rows':[],'review_rows':doc['_rentroll_review_rows']})
    return result


def money(value):
    if value is None or value=='': return None
    if not isinstance(value,(str,int)) or isinstance(value,bool):
        raise ReadError('明細の金額は円単位の数値で指定してください。')
    value=str(value).strip().replace(',','')
    if not re.fullmatch(r'\d{1,12}(?:\.\d{1,2})?',value):
        raise ReadError('金額は円単位で入力してください。単位付き・負数・指数表記は使用できません。')
    try: number=Decimal(value)
    except InvalidOperation: raise ReadError('明細の金額を確認してください。') from None
    if number>=Decimal('1000000000000'): raise ReadError('明細金額が上限を超えています。')
    return number


def calculate(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('rows'),list):
        raise ReadError('集計する明細を確認してください。')
    rows=payload['rows']
    if not 1<=len(rows)<=3600: raise ReadError('集計明細は1〜3,600行で指定してください。')
    coverage=payload.get('coverage_confirmed') is True
    result=[]; ids=set(); source_keys=set(); business_keys=set(); issues=[]
    sums={'current':Decimal(0),'full':Decimal(0)}; missing={'current':[],'full':[]}
    dates=set(); taxes=set(); included=0
    for line in rows:
        if not isinstance(line,dict):raise ReadError('明細の形式を確認してください。')
        item={}
        for key in ('id','unit','component','period','tax_basis','as_of','exclusion_reason'):
            v=line.get(key,'')
            if not isinstance(v,str) or len(v)>300:raise ReadError('明細の文字項目を確認してください。')
            item[key]=v.strip()
        if not item['id'] or item['id'] in ids:raise ReadError('明細IDが空か重複しています。')
        ids.add(item['id'])
        if type(line.get('include')) is not bool:raise ReadError('明細の採用・除外を選択してください。')
        item['include']=line['include']
        source=line.get('source')
        if not isinstance(source,dict):raise ReadError('明細の出典がありません。')
        for key in ('document_id','sha256','label','quote'):
            if not isinstance(source.get(key),str) or len(source[key])>(4000 if key=='quote' else 300):raise ReadError('明細の出典を確認してください。')
        if not re.fullmatch(r'[0-9a-f]{64}',source['sha256']):raise ReadError('明細の資料照合値を確認してください。')
        if any(type(source.get(k)) is not int or source[k]<1 for k in ('page','row')):raise ReadError('明細の出典位置を確認してください。')
        item['source']=source
        for side in ('current','full'):
            number=money(line.get(side+'_amount'))
            item[side+'_amount']=None if number is None else format(number,'f')
        item['annual_current']=None;item['annual_full']=None;item['issues']=[]
        if not item['include']:
            if not item['exclusion_reason']:raise ReadError('除外する明細には理由を記入してください。')
            result.append(item);continue
        included+=1
        problems=item['issues']
        if item['component'] not in COMPONENTS:problems.append('収入区分が不明')
        if item['component']=='one_time':problems.append('敷金等の一時金は年間収入から除外してください')
        if not item['unit']:problems.append('部屋・区画が不明')
        if item['period'] not in ('monthly','annual'):problems.append('月額／年額が不明')
        if item['tax_basis'] not in ('inclusive','exclusive','exempt'):problems.append('税込／税抜／非課税が不明')
        else:taxes.add(item['tax_basis'])
        try:
            if date.fromisoformat(item['as_of']).isoformat()!=item['as_of']:raise ValueError()
            dates.add(item['as_of'])
        except ValueError:problems.append('基準日が不明または不正')
        sk=(source['sha256'],source['page'],source['row'],item['component'])
        bk=(item['unit'],item['component'])
        if sk in source_keys:problems.append('同じ資料行・収入区分の重複')
        if bk in business_keys:problems.append('同じ部屋・区画の収入区分が重複。二重計上を確認してください')
        source_keys.add(sk);business_keys.add(bk)
        if re.search(r'合計|総計|小計|subtotal|total',item['unit'],re.I):problems.append('合計行を明細と一緒に採用できません')
        for side in ('current','full'):
            amount=money(item[side+'_amount'])
            if amount is None:missing[side].append(item['id'])
            elif not problems:
                annual=amount*(12 if item['period']=='monthly' else 1)
                sums[side]+=annual;item['annual_'+side]=format(annual,'f')
        if problems:issues.extend(f"{item['id']}：{p}" for p in problems)
        result.append(item)
    if not coverage:issues.append('対象の部屋・区画と収入項目を全て確認してください')
    if not included:issues.append('採用する明細がありません')
    if len(dates)>1:issues.append('異なる基準日の明細をまとめて確定できません')
    # Exempt rent may coexist with tax-inclusive parking, but exclusive amounts cannot
    # be mixed with inclusive ones. No implied consumption-tax rate or conversion.
    if 'inclusive' in taxes and 'exclusive' in taxes:issues.append('税込と税抜が混在しています。換算せず確認待ちにしています')
    output={'rows':result,'issues':issues,'coverage_confirmed':coverage,'included_count':included,
            'excluded_count':len(rows)-included,'as_of':next(iter(dates)) if len(dates)==1 else None,
            'tax_basis':sorted(taxes),'totals':{},'missing':missing,'subtotals':{k:format(v,'f') for k,v in sums.items()}}
    for side,key in [('current','current_annual_income_yen'),('full','full_annual_income_yen')]:
        if sums[side]>=Decimal('10000000000000'):raise ReadError('年間合計が上限を超えています。')
        output['totals'][key]=None if issues or missing[side] else format(sums[side],'f')
    return output
