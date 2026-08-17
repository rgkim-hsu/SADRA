#!/usr/bin/env python3
"""
generate_output_words.py

생성된 ADR 파일에서 문서별 출력 단어 수(output_words)를 추출하여
document_metadata.csv를 생성하는 유틸리티 스크립트.

사용법:
  python generate_output_words.py <ADR_출력_디렉토리> [--output document_metadata.csv]

ADR 파일 이름 형식 예시:
  1020190092258B1_9_1_gemma_adr.md
  TRKO202100009640_qwen_adr.md

출력:
  document_id, model, output_words 컬럼을 가진 CSV 파일
"""
import os
import sys
import re
import glob
import csv

def count_words(filepath: str) -> int:
    with open(filepath, "r", encoding="utf-8") as f:
        return len(re.findall(r"\w+", f.read()))
    except Exception as e:
        print(f"  ⚠ {filepath}: {e}")
        return 0

LOCAL_MODELS = ["gemma", "ministral", "qwen"]
REFERENCE_MODELS = ["chatgpt", "claude", "gemini", "mistral", "qwen3_6"]

def extract_doc_model(filename: str):
    name = os.path.splitext(filename)[0]
    parts = name.split("_")          # PAT-01 / gemma / ADR
    if len(parts) < 2:
        return None, None
    doc_id, model = parts[0], parts[1]
    if model in REFERENCE_MODELS:    # 레퍼런스 ADR은 제외
        return None, None
    return (doc_id, model) if model in LOCAL_MODELS else (None, None)

def main():
    if len(sys.argv) < 2:
        print("사용법: python generate_output_words.py <ADR_출력_디렉토리>")
        print("  예: python generate_output_words.py D:\\KIIT_paper_source_code\\output\\adr")
        sys.exit(1)
    
    adr_dir = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "document_metadata.csv"
    
    # ADR 파일 탐색 (마크다운 및 텍스트 파일)
    patterns = ["*.md", "*.txt", "*.markdown"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(adr_dir, "**", pat), recursive=True))
    
    if not files:
        print(f"[ERROR] '{adr_dir}'에서 ADR 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    print(f"발견된 ADR 파일: {len(files)}개")
    
    rows = []
    for fpath in sorted(files):
        fname = os.path.basename(fpath)
        doc_id, model = extract_doc_model(fname)
        wc = count_words(fpath)
        rows.append({"document_id": doc_id, "model": model, 
                      "output_words": wc, "filepath": fpath})
        print(f"  {fname}: doc={doc_id}, model={model}, words={wc}")
    
    # CSV 저장
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["document_id", "model", "output_words"])
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in ["document_id", "model", "output_words"]})
    
    print(f"\n저장: {output_csv} ({len(rows)}행)")
    print(f"이 파일을 data/ 디렉토리에 복사한 후 statistical_analysis.py를 재실행하면")
    print(f"§4.3 회귀 분석에서 output_words가 자동으로 반영됩니다.")


if __name__ == "__main__":
    main()
