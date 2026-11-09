#!/usr/bin/env python3
"""Approved-template-only draft writer. Offline; no API, macros, or PDF export."""
from __future__ import annotations
import argparse, json, math, re, sys, zipfile, hashlib
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import xml.etree.ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("x", NS)
ET.register_namespace("r", RNS)

def tag(name: str) -> str:
    return "{" + NS + "}" + name

class InputError(ValueError):
    pass

def numeric(value, label):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise InputError(label + "は真偽値ではなく数値で指定してください。")
    if not isinstance(value, (int, float, Decimal)):
        raise InputError(label + "は単位やカンマを付けず、数値で指定してください。")
    value = Decimal(str(value))
    if not value.is_finite() or value < 0 or value > Decimal("9999999999999") or (value!=0 and value<Decimal("0.000001")):
        raise InputError(label + "には0または0.000001以上・10兆未満の数値を指定してください。")
    return value

def serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days

def date_value(raw):
    if raw is None or raw == "":
        return None, None
    if not isinstance(raw, str):
        raise InputError("築年月は文字列で指定してください。")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            d = date.fromisoformat(raw)
        except ValueError as e:
            raise InputError("築年月日が存在しません。") from e
        return serial(d), d
    # Validate ISO partial dates without inventing their missing precision.
    if re.fullmatch(r"\d{4}-\d{2}", raw):
        try: date.fromisoformat(raw + '-01')
        except ValueError as e: raise InputError("築年月の月が不正です。") from e
    if len(raw)>300: raise InputError("築年月が長すぎます。")
    if any(ord(ch)<32 for ch in raw): raise InputError("築年月に使用できない文字があります。")
    return raw, None

def safe_text(value, label, limit):
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(label + "は文字列で指定してください。")
    if len(value) > limit:
        raise InputError(label + f"が長いため、{limit}文字以内に整理してください。自動切捨てはしません。")
    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in value):
        raise InputError(label + "に使用できない制御文字があります。")
    return value

def validate(payload, spec):
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), dict):
        raise InputError('入力は {"fields": {...}, "as_of": "YYYY-MM-DD"} 形式です。')
    extra = set(payload["fields"]) - set(spec["fields"])
    if extra:
        raise InputError("見本にない項目は出力できません: " + ", ".join(sorted(extra)))
    transaction=payload["fields"].get("transaction")
    if transaction not in (None,"","媒介","代理","売主"):
        raise InputError("取引形態は媒介・代理・売主から選択してください。")
    raw_date = payload.get("as_of")
    try:
        created = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
    except ValueError as e:
        raise InputError("作成日はYYYY-MM-DD形式で指定してください。") from e
    if created is None:
        raise InputError("作成日as_ofを指定してください。これは物件の確認日とは別です。")
    values = {}
    built = None
    for key, info in spec["fields"].items():
        value = payload["fields"].get(key)
        if key in spec["numeric_fields"]:
            values[key] = numeric(value, info["label"])
        elif key == "built_date":
            values[key], built = date_value(value)
        else:
            limit = spec["limits"]["remarks_chars"] if key == "remarks" else spec["limits"]["field_chars"]
            values[key] = safe_text(value, info["label"], limit)
    if built and built > created:
        raise InputError("築年月日が作成日より未来です。原資料を確認してください。")
    if values.get("absolute_height") and '低層住居専用地域' not in (values.get('land_use_zone') or ''):
        raise InputError("完成見本の注記では絶対高さは低層の場合のみ記載します。用途地域を確認し、低層以外の高さ制限は高度地区欄へ記載してください。")
    partial=values.get('built_date')
    if isinstance(partial,str) and re.fullmatch(r"\d{4}(?:-\d{2})?",partial):
        if partial>(created.isoformat()[:len(partial)]):raise InputError("築年月が作成日より未来です。原資料を確認してください。")
    values["handover"]="相談"
    return values, created, built

def calc(values, created, built):
    def n(key): return values.get(key)
    p, la, ba = n("price_yen"), n("land_area_m2"), n("building_area_m2")
    coefficient = Decimal("0.3025")  # Original supplied template's m² -> tsubo coefficient.
    land_tsubo = la * coefficient if la is not None else None
    result = {
        "W19": land_tsubo,
        "W30": ba * coefficient if ba is not None else None,
        "Y5": p / land_tsubo if p is not None and land_tsubo and land_tsubo > 0 else None,
        "Y7": (n("full_annual_income_yen") / p).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP) if n("full_annual_income_yen") is not None and p and p > 0 else None,
        "Y9": (n("current_annual_income_yen") / p).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP) if n("current_annual_income_yen") is not None and p and p > 0 else None,
        "Y21": n("road_value_yen_m2") * la if n("road_value_yen_m2") is not None and la is not None else None,
        "Y32": created.year - built.year - ((created.month, created.day) < (built.month, built.day)) if built else None,
    }
    return result

def col_index(address):
    letters = re.match(r"[A-Z]+", address).group(0)
    out = 0
    for c in letters:
        out = out * 26 + ord(c) - 64
    return out

def get_cell(root, address):
    sd = root.find(tag("sheetData"))
    row_no = int(re.search(r"\d+", address).group(0))
    row = next((r for r in sd if int(r.get("r")) == row_no), None)
    if row is None:
        row = ET.Element(tag("row"), {"r": str(row_no)})
        idx = next((i for i,r in enumerate(sd) if int(r.get("r")) > row_no), len(sd))
        sd.insert(idx, row)
    cell = next((c for c in row if c.get("r") == address), None)
    if cell is None:
        cell = ET.Element(tag("c"), {"r": address})
        idx = next((i for i,c in enumerate(row) if col_index(c.get("r")) > col_index(address)), len(row))
        row.insert(idx, cell)
    return cell

def set_value(root, address, value):
    cell = get_cell(root, address)
    for child in list(cell):
        if child.tag in {tag("v"), tag("f"), tag("is")}:
            cell.remove(child)
    cell.attrib.pop("t", None)
    if value is None:
        return
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        ET.SubElement(cell, tag("v")).text = str(value)
    else:
        # Inline string rather than a formula: untrusted =, +, @ text is never executed.
        cell.set("t", "inlineStr")
        t = ET.SubElement(ET.SubElement(cell, tag("is")), tag("t"))
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(value)

def set_formula(root, address, formula, cached):
    set_value(root, address, None)
    cell = get_cell(root, address)
    ET.SubElement(cell, tag("f")).text = formula.lstrip("=")
    if cached is None:
        cell.set("t", "str")
        ET.SubElement(cell, tag("v")).text = ""
    else:
        ET.SubElement(cell, tag("v")).text = str(cached)

def load_template(path):
    with zipfile.ZipFile(path) as z:
        if any(i.file_size > 8_000_000 for i in z.infolist()) or sum(i.file_size for i in z.infolist()) > 24_000_000:
            raise InputError("指定テンプレートの容量が想定外です。配布された白紙テンプレートを使用してください。")
        parts = {n: z.read(n) for n in z.namelist()}
    if any("vbaproject" in n.lower() or n.startswith("xl/externalLinks/") for n in parts):
        raise InputError("マクロ／外部リンクを含むテンプレートは使用できません。")
    expected = {"xl/workbook.xml", "xl/worksheets/sheet1.xml"}
    if not expected.issubset(parts):
        raise InputError("テンプレートの形式が異なります。")
    workbook = ET.fromstring(parts["xl/workbook.xml"])
    sheets = workbook.find(tag("sheets"))
    if len(sheets) != 1 or sheets[0].get("name") != "概要書":
        raise InputError("配布済みの1シート構成「概要書」を使用してください。")
    # Property-specific hyperlinks in relationship files survive clearing cell text.
    # Drop links in the serialization boundary, including stale targets not visible in cells.
    for part, raw in list(parts.items()):
        if part.endswith('.rels'):
            rels=ET.fromstring(raw)
            changed=False
            for rel in list(rels):
                if rel.get('Type','').endswith('/hyperlink'):
                    rels.remove(rel);changed=True
                elif rel.get('TargetMode')=='External':
                    raise InputError("外部部品を参照するテンプレートは使用できません。")
            if changed:parts[part]=ET.tostring(rels,encoding='utf-8',xml_declaration=True)
        elif part.startswith('xl/worksheets/') and part.endswith('.xml'):
            root=ET.fromstring(raw)
            for link in list(root.findall(tag('hyperlinks'))):root.remove(link)
            parts[part]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    return parts

def write_draft(payload, target, template, spec):
    values, created, built = validate(payload, spec)
    if spec.get("template_sha256") and hashlib.sha256(template.read_bytes()).hexdigest()!=spec["template_sha256"]:
        raise InputError("採用テンプレートの照合値が一致しません。管理者が正本と変更内容を確認してください。")
    parts = load_template(template)
    # Normalize drawing image relationships to package-relative paths for reader compatibility.
    for relname, relbytes in list(parts.items()):
        if relname.startswith("xl/drawings/_rels/") and relname.endswith(".rels"):
            relroot = ET.fromstring(relbytes)
            for rel in relroot:
                t = rel.get("Target", "")
                if t.startswith("/xl/media/"): rel.set("Target", "../media/" + t.rsplit("/", 1)[-1])
            parts[relname] = ET.tostring(relroot, encoding="utf-8", xml_declaration=True)
    root = ET.fromstring(parts["xl/worksheets/sheet1.xml"])
    # Empty formula nodes in the imported template are not real calculations.
    for cell in root.iter(tag("c")):
        for formula in list(cell.findall(tag("f"))):
            if not formula.text:cell.remove(formula)
    company_prefix = {
        "company_name": "社名： ", "company_address": "住所： ",
        "company_phone": "電話： ", "agent": "担当： ",
    }
    for key, info in spec["fields"].items():
        value = values[key]
        if key in company_prefix:
            value = company_prefix[key] + (value or "")
        set_value(root, info["cell"], value)
    set_value(root, spec["as_of_cell"], serial(created))
    calculated = calc(values, created, built)
    for addr, formula in spec["derived_cells"].items():
        set_formula(root, addr, formula, calculated[addr])
    # Keep A4 portrait / one-page print settings explicitly; the artifact importer does not retain all print metadata.
    spr = root.find(tag("sheetPr"))
    if spr is None:
        spr = ET.Element(tag("sheetPr")); root.insert(0, spr)
    fit = spr.find(tag("pageSetUpPr"))
    if fit is None: fit = ET.SubElement(spr, tag("pageSetUpPr"))
    fit.set("fitToPage", "1")
    margins = root.find(tag("pageMargins"))
    if margins is not None:
        margins.attrib.update({"left":"0.23622","right":"0.23622","top":"0.15","bottom":"0.15","header":"0","footer":"0"})
    setup = root.find(tag("pageSetup"))
    if setup is None:
        setup = ET.Element(tag("pageSetup"))
        idx = list(root).index(margins)+1 if margins is not None else len(root)
        root.insert(idx, setup)
    setup.attrib.update({"paperSize":"9","orientation":"portrait","fitToWidth":"1","fitToHeight":"1"})
    wb = ET.fromstring(parts["xl/workbook.xml"])
    dns = wb.find(tag("definedNames"))
    if dns is None:
        dns = ET.Element(tag("definedNames"))
        idx = list(wb).index(wb.find(tag("sheets")))+1
        wb.insert(idx, dns)
    for dn in list(dns):
        if dn.get("name")=="_xlnm.Print_Area": dns.remove(dn)
    ET.SubElement(dns,tag("definedName"),{"name":"_xlnm.Print_Area","localSheetId":"0"}).text="'概要書'!$A$1:$AG$59"
    cp = wb.find(tag("calcPr"))
    if cp is not None: cp.attrib.update({"calcMode":"auto","fullCalcOnLoad":"1"})
    parts["xl/workbook.xml"] = ET.tostring(wb,encoding="utf-8",xml_declaration=True)
    # No PDF and no extra sheets are generated.
    parts["xl/worksheets/sheet1.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise InputError("同名の出力が既にあります。手直し済みを保護するため、別の出力名かフォルダを指定してください。")
    if target.resolve() == template.resolve():
        raise InputError("テンプレート自身は上書きできません。")
    with target.open("xb") as f:
        with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as z:
            for name, content in parts.items():
                z.writestr(name, content)
    with zipfile.ZipFile(target) as z:
        if z.testzip():
            raise InputError("出力の整合性確認に失敗しました。")
    return calculated

def main(argv=None):
    parser = argparse.ArgumentParser(description="物件概要・編集用Excelを作成します。PDF化はしません。")
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--mode", choices=["common", "both"], default="common")
    args = parser.parse_args(argv)
    home = Path(__file__).resolve().parent
    if args.case.stat().st_size > 200_000:
        raise InputError("入力データが大きすぎます。物件概要の項目だけに整理してください。")
    payload = json.loads(args.case.read_text(encoding="utf-8-sig"))
    spec = json.loads((home / "data/field_map.json").read_text(encoding="utf-8"))
    template = home / "data/property_overview.xlsx"
    filenames = ["物件概要_編集用下書き.xlsx"] if args.mode == "common" else ["業者向け_編集用下書き.xlsx", "一般顧客向け_編集用下書き.xlsx"]
    # Preflight all targets, so re-running never partially replaces manual edits.
    for name in filenames:
        if (args.out / name).exists():
            raise InputError("出力先に同名ファイルがあります。新しい出力フォルダを指定してください。")
    validate(payload, spec)
    for name in filenames:
        write_draft(payload, args.out/name, template, spec)
        print("作成済み:", args.out/name)
    print("Excelで手直しし、掲載内容と印刷範囲を確認した後、ご本人がPDF保存してください。")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InputError, ValueError, OSError, zipfile.BadZipFile) as exc:
        # Local input validation only. No telemetry or external submission.
        print("処理を止めました:", str(exc), file=sys.stderr)
        raise SystemExit(2)
