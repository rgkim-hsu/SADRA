#!/usr/bin/env python3
"""
generate_manifest.py
Excel(xlsx) 데이터에서 document_manifest.csv를 자동 생성합니다.
외부 패키지 불필요 — Python 표준 라이브러리만 사용합니다.

사용법: python generate_manifest.py [data_dir]
  data_dir: similarity_*_as_reference*.xlsx 파일이 있는 폴더 (기본: 현재 폴더)
"""
import os, sys, glob, csv, zipfile, xml.etree.ElementTree as ET


def read_xlsx_sheet1(filepath):
    """openpyxl 없이 xlsx의 Sheet1을 읽어 list[dict]로 반환."""
    rows = []
    with zipfile.ZipFile(filepath, "r") as zf:
        # shared strings
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            tree = ET.parse(zf.open("xl/sharedStrings.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in tree.findall(".//s:si", ns):
                parts = [t.text or "" for t in si.findall(".//s:t", ns)]
                shared.append("".join(parts))

        # sheet1
        tree = ET.parse(zf.open("xl/worksheets/sheet1.xml"))
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        sheet_rows = tree.findall(".//s:sheetData/s:row", ns)

        header = []
        for i, row in enumerate(sheet_rows):
            vals = []
            for c in row.findall("s:c", ns):
                t = c.get("t", "")
                v_el = c.find("s:v", ns)
                if v_el is None or v_el.text is None:
                    vals.append("")
                elif t == "s":
                    vals.append(shared[int(v_el.text)])
                else:
                    vals.append(v_el.text)
            if i == 0:
                header = vals
            else:
                rows.append(dict(zip(header, vals)))
    return rows


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    pattern = os.path.join(data_dir, "similarity_*_as_reference*.xlsx")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"Error: No Excel files matching '{pattern}'")
        sys.exit(1)

    # 첫 번째 Excel에서 document_id, doc_type 추출
    print(f"Reading: {os.path.basename(files[0])}")
    rows = read_xlsx_sheet1(files[0])

    seen = set()
    manifest = []
    for r in rows:
        doc_id = r.get("document_id", "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        is_patent = doc_id.startswith("10")
        manifest.append({
            "document_id": doc_id,
            "doc_type": "patent" if is_patent else "report",
            "source": "KIPRIS" if is_patent else "RDA/MAFRA",
            "title": "(to be filled)",
            "url": "https://www.kipris.or.kr" if is_patent else "",
        })

    manifest.sort(key=lambda x: (x["doc_type"], x["document_id"]))

    out_path = os.path.join(data_dir, "document_manifest.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["document_id", "doc_type", "source", "title", "url"])
        w.writeheader()
        w.writerows(manifest)

    n_patent = sum(1 for m in manifest if m["doc_type"] == "patent")
    n_report = sum(1 for m in manifest if m["doc_type"] == "report")
    print(f"Generated: {out_path}")
    print(f"  Total: {len(manifest)} documents (Patents: {n_patent}, Reports: {n_report})")


if __name__ == "__main__":
    main()
