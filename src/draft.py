"""Document intake, sheet selection and auditable rent-roll checks."""
import base64
import io
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import PurePosixPath

from PIL import Image, ImageOps
from pypdf import PdfReader
from extraction import ReadError, candidate
from rentroll import tables


def norm(s):
    return unicodedata.normalize('NFKC', str(s)).strip()


def guess(name):
    for pattern, kind in [(r'レント|rent|収支明細', 'rentroll'), ('管理委託', 'management'),
                          ('土地|地積', 'land'), ('建物.*(謄本|登記)', 'building'),
                          ('用途地域|都市計画', 'zoning'), ('修繕', 'repair'),
                          ('評価証明|固定資産', 'tax'), ('間取|図面', 'drawing'),
                          ('住宅地図', 'map'), (r'概要|\.(txt|md)$', 'notes')]:
        if re.search(pattern, name, re.I):
            return kind
    return 'unknown'


def _unpack(items, warnings):
    result = []
    total = 0
    for item in items:
        raw = base64.b64decode(item['raw_b64'], validate=True)
        name = item['name']
        if not name.lower().endswith('.zip'):
            if re.search('成果物|完成品|見本|サンプル|(?:会社)?ロゴ', unicodedata.normalize('NFC',name)):
                warnings.append(name+'は見本・ロゴとして入力から除外しました。')
                continue
            result.append((name, raw, item['kind']))
            total += len(raw)
            continue
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 200 or sum(i.file_size for i in members) > 40_000_000:
                raise ReadError('ZIPの展開上限を超えています。資料を分けてください。')
            for i in members:
                path = i.filename
                if not i.flag_bits & 0x800:
                    for codec in ('utf-8', 'cp932'):
                        try:
                            path = path.encode('cp437').decode(codec)
                            break
                        except UnicodeError:
                            pass
                parts = PurePosixPath(path.replace('\\', '/'))
                if parts.is_absolute() or '..' in parts.parts or i.flag_bits & 1:
                    raise ReadError('暗号化されたZIPまたは不正なパスは読めません。')
                if i.is_dir() or any(p.startswith('.') or p == '__MACOSX' for p in parts.parts):
                    continue
                filename = unicodedata.normalize('NFC', parts.name)
                if re.search('成果物|完成品|見本|サンプル|(?:会社)?ロゴ', filename):
                    warnings.append(filename + 'は見本・ロゴとして入力から除外しました。')
                    continue
                if parts.suffix.lower() not in ('.pdf','.png','.jpg','.jpeg','.webp','.xlsx','.txt','.md','.csv'):
                    warnings.append(filename + 'は対象外の形式です。')
                    continue
                total += i.file_size
                if i.file_size > 8*1024**2 or total > 25*1024**2 or len(result) >= 10:
                    raise ReadError('ZIP内を含め資料は1件8MB、合計25MB、10点以内にしてください。')
                result.append((filename, archive.read(i), guess(filename)))
    if len(result) > 10 or total > 25*1024**2:
        raise ReadError('展開後の資料は10点・合計25MBまでです。')
    return result


def inputs(items, warnings):
    result = []
    total = 0
    for item in items:
        try:
            batch = _unpack([item], warnings)
        except (ReadError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
            warnings.append(item['name']+'：読み込み対象から外しました（'+str(exc)[:160]+'）。')
            continue
        total += sum(len(raw) for _,raw,_ in batch)
        if len(result)+len(batch)>10 or total>25*1024**2:
            raise ReadError('展開した資料が10点または合計25MBを超えました。')
        result.extend(batch)
    return result


def select_sheets(doc):
    paired = list(zip(doc['pages'], doc['sheets']))
    rolls = [(p,s) for p,s in paired if re.search('レントロール|rent.?roll|賃貸一覧', s['name'], re.I)]
    if rolls:
        if len(rolls) != len(paired):
            doc['warnings'].append('レントロールのシートを使用し、同じExcel内の別シートは除外しました。')
        doc['kind'] = 'rentroll'
        doc['pages'], doc['sheets'] = map(list, zip(*rolls))


def roll_candidates(doc):
    found = []
    for table in tables(doc):
        rows = table['rows']
        for row in rows[:8]:
            for col, value in row['cells'].items():
                title = re.fullmatch(r'(.{1,100}?)\s+(?:レントロール|賃貸条件一覧)(?:\s*[（(].*)?', norm(value))
                if title:
                    found.append(candidate('property_name', title[1].strip(), doc, table['page'],
                                           f"{table['label']} {col}{row['row']} = {value}", 'sheet-title'))
        header = next((r for r in rows[:12] if any(norm(v) in ('号室','部屋','部屋番号','区画') for v in r['cells'].values())), None)
        if not header:
            continue
        cols = {re.sub(r'\s+', '', norm(v)):k for k,v in header['cells'].items()}
        unit = next(cols[x] for x in ('号室','部屋','部屋番号','区画') if x in cols)
        kind = next((cols[x] for x in ('タイプ','間取り','間取') if x in cols), None)
        entries = [r for r in rows if r['row'] > header['row'] and r['cells'].get(unit)]
        details = [r for r in entries if not re.search('小計|総計|合計|計$|注記', r['cells'][unit])]
        rooms = [r for r in details if re.fullmatch(r'[A-Za-z]?\d{1,5}[A-Za-z]?(?:号室)?', norm(r['cells'][unit]))]
        unique_rooms = len({norm(r['cells'][unit]) for r in rooms}) == len(rooms)
        if kind and rooms and unique_rooms and all(r['cells'].get(kind) for r in rooms):
            mixes = Counter(norm(r['cells'][kind]) for r in rooms)
            if all(re.fullmatch(r'(?:[1-9][SLDKR]+|ワンルーム|STUDIO)', m, re.I) for m in mixes):
                mix = '、'.join(f'{m}×{n}戸' for m,n in mixes.items())
                doc['warnings'].append('間取り：レントロール明細には'+mix+'の記載があります。概要書への採用は建物図面または管理委託契約書で確認します。')
        status_col = next((c for h,c in cols.items() if re.search('入居状況|稼働状況|入居状態',h)), None)
        if status_col:
            grouped = {}
            for row in details:
                note = str(row['cells'].get(status_col,'')).strip()
                if not re.search('退去|入居中|空室|空き|社宅|契約中|賃貸中|募集中|自用|営業所利用', note):
                    continue
                grouped.setdefault(note,[]).append((row['cells'][unit],row['row']))
            for note, matches in grouped.items():
                labels = '・'.join(x[0] for x in matches)
                cite = '、'.join(f"{status_col}{n}" for _,n in matches)
                found.append(candidate('remarks',f'{labels}：{note}',doc,table['page'],
                                       f"{table['label']} {cite} = {note}",'occupancy-note'))
        for row in entries:
            if '小計' not in row['cells'][unit]:
                continue
            stated = re.search(r'住戸\s*(\d+)\s*戸', ' '.join(row['cells'].values()))
            if stated and int(stated[1]) != len(rooms):
                doc['warnings'].append(f"総戸数：{table['label']}の小計は住戸{stated[1]}戸、号室付き明細は{len(rooms)}戸です。総戸数は空欄にしました。")
        # Uncached formula cells are not zero. Reconcile explicit monthly net
        # components with the stated annual total when all detail cells are numeric.
        rent = cols.get('月額家賃(税抜)')
        common = cols.get('月額共益費')
        if details and rent and common:
            amounts = [r['cells'].get(c,'') for r in details for c in (rent,common)]
            printed = re.search(r'想定年間総収入\s*\(税抜\)\s*:\s*([\d,]+)円', norm(' '.join(v for r in entries for v in r['cells'].values())))
            if printed and all(re.fullmatch(r'[\d,]+', n) for n in amounts):
                annual = 12 * sum(int(n.replace(',','')) for n in amounts)
                stated = int(printed[1].replace(',',''))
                if stated != annual:
                    doc['warnings'].append(f'年間収入：明細の月額家賃・共益費（駐車場等を含む）を年換算すると{annual:,}円、表の想定額は{stated:,}円です。差額{abs(annual-stated):,}円の内訳を確認してください。')
        # Read a declared total only if the scope, side, currency, tax and
        # values of all included rows support it. Never infer full from current.
        total_rows = [r for r in entries if norm(r['cells'][unit]) in ('合計','総合計','総計')]
        for side,key in [('現況','current_annual_income_yen'),('満室','full_annual_income_yen')]:
            choices=[(h,c) for h,c in cols.items() if side in h and ('年' in h or '月' in h)
                     and any(x in h for x in ('合計','収入','収益','総額'))
                     and any(x in h for x in ('税込','税抜','非課税')) and '万' not in h]
            if len(total_rows)!=1 or len(choices)!=1 or not details or len({r['cells'][unit] for r in details})!=len(details):
                continue
            h,c=choices[0]
            amounts=[r['cells'].get(c,'').replace(',','') for r in details]
            stated=total_rows[0]['cells'].get(c,'').replace(',','')
            if not all(n.isdigit() for n in amounts+[stated]) or sum(map(int, amounts))!=int(stated):
                doc['warnings'].append(side+'年間収入：明細と合計行が一致しないか、金額が空欄です。')
                continue
            annual=int(stated)*(12 if '月' in h else 1)
            if annual < 10**13:
                found.append(candidate(key,annual,doc,table['page'],f"{table['label']} {c}{total_rows[0]['row']} {h}={stated}、{len(details)}明細と一致", 'rentroll-verified-total'))
    return found


def scan_images(doc, raw, remaining):
    """OCR only full-page single-image PDFs and image files, never guess order of layers."""
    pages = [p for p in doc['pages'] if not p['text'].strip() and p.get('visual_required')]
    if not pages:
        return []
    pdf = PdfReader(io.BytesIO(raw)) if doc['name'].lower().endswith('.pdf') else None
    # Cover the title, schedules and next page before boilerplate.
    order = pages[:1] + pages[-1:] + pages[1:-1] if len(pages)>1 else pages
    jobs = []
    for p in order[:min(4, remaining)]:
        try:
            if pdf:
                pg = pdf.pages[p['page']-1]
                if len(pg.images)!=1:
                    continue
                im = pg.images[0].image
                if pg.rotation:
                    im = im.rotate(-pg.rotation, expand=True)
            else:
                im = Image.open(io.BytesIO(raw))
            if im.width*im.height > 25_000_000:
                continue
            im = ImageOps.exif_transpose(im).convert('L')
            im.thumbnail((2050,2050))
            data = io.BytesIO()
            im.save(data,'PNG')
            if data.tell()>2_500_000:
                continue
            jobs.append({'id':doc['id'],'page':p['page'],'image':base64.b64encode(data.getvalue()).decode()})
        except Exception:
            continue
    return jobs
