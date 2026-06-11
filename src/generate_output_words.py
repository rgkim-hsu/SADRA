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
    """파일의 단어 수를 반환."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read()
        # 마크다운 문법 요소 제거 후 단어 수 카운트
        text = re.sub(r"[#*|`\-\[\]()>]", " ", text)
        words = text.split()
        return len(words)
    except Exception as e:
        print(f"  ⚠ {filepath}: {e}")
        return 0


def extract_doc_model(filename: str):
    """파일명에서 document_id와 model을 추출."""
    # 패턴: {document_id}_{model}_adr.md 또는 유사 형식
    name = os.path.splitext(filename)[0]
    
    # 모델 이름 후보
    models = ["gemma", "ministral", "qwen"]
    
    for model in models:
        if f"_{model}" in name.lower():
            doc_id = name.lower().split(f"_{model}")[0]
            return doc_id.strip("_"), model
    
    return name, "unknown"


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
