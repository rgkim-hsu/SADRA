#!/usr/bin/env python3
"""
generate_manifest.py
Excel 데이터에서 document_manifest.csv를 자동 생성합니다.
사용법: python generate_manifest.py ./data/
"""
import os, sys, glob, pandas as pd

data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
pattern = os.path.join(data_dir, "similarity_*_as_reference*.xlsx")
files = glob.glob(pattern)
if not files:
    print(f"Error: No Excel files found in {data_dir}")
    sys.exit(1)

df = pd.read_excel(files[0])
docs = df[["document_id", "doc_type"]].drop_duplicates().sort_values("document_id")

manifest = []
for _, row in docs.iterrows():
    doc_id = str(row["document_id"])
    source_type = "patent" if doc_id.startswith("10") else "report"
    source = "KIPRIS" if source_type == "patent" else "RDA/MAFRA"
    manifest.append({
        "document_id": doc_id,
        "doc_type": source_type,
        "source": source,
        "title": "(to be filled)",
        "url": "https://www.kipris.or.kr" if source_type == "patent" else ""
    })

out = pd.DataFrame(manifest)
out_path = os.path.join(data_dir, "document_manifest.csv")
out.to_csv(out_path, index=False)
print(f"Generated {out_path} with {len(out)} documents")
print(f"  Patents: {len(out[out['doc_type']=='patent'])}")
print(f"  Reports: {len(out[out['doc_type']=='report'])}")
