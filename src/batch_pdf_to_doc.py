"""
배치 PDF → 문서 생성 스크립트 (v2)

위치: 2_CODE/scripts/batch_pdf_to_doc.py (저장소 루트에서 `cd 2_CODE` 후 `python scripts/batch_pdf_to_doc.py`)

app_vision.py와 동일한 알고리즘으로 폴더 내 모든 PDF를 순차 처리한다.
각 PDF마다 시스템개념도(1_시스템개념도) 중 다이어그램 유사도가 가장 높은
이미지 1장만 선택하여 ADR → PRD → TestPlan을 생성한다.

알고리즘 동일성:
  - 이미지 추출: extract_images_from_pdf (pdf_image_extractor_scanned)
  - 텍스트 추출: extract_text_from_pdf (pdf_text_extractor)
  - 이미지 분류: load_convnext_model + process_folder_vision (VLM은 qwen 고정, 선택지 2번 Ollama 태그)
  - 문서 생성:   RAGSystem.process_image → PRDGenerator → TestPlanGenerator (선택한 LLM)

개선 사항:
  - config_models, utils_common 모듈 사용
  - 중복 함수 제거
  - generated_docs: ADR/PRD/TestPlan 각 파일이 존재하고 비어 있지 않으면 해당 단계만 스킵

산출물 루트: 저장소 `3_RESULT/batch_results/<pdf_stem>/` (app.py·app_vision.py와 경로 분리)
"""

import os
import sys
import shutil
import time
import traceback
from datetime import datetime
from pathlib import Path

import torch

# 2_CODE 루트 및 하위 모듈 경로 (scripts/ 에서 실행)
_CODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CODE_ROOT / "core"))
from code_paths import setup_project_paths
from embeddings_config import RAG_EMBEDDING_DISPLAY_NAME

REPO_ROOT, CODE_ROOT = setup_project_paths(include_classification_extras=True)

from pdf_image_extractor_scanned import extract_images_from_pdf
from pdf_text_extractor import extract_text_from_pdf
from rag_module import RAGSystem
from generate_PRD import PRDGenerator
from generate_testplan import TestPlanGenerator

# 공통 모듈 import
try:
    from config_models import LLM_CHOICES, short_llm_tag_for_filename
    from utils_common import (
        list_images, list_texts, write_text_file,
        sanitize_filename, sanitize_model_name_for_path,
        unique_doc_filename_stem,
    )
    COMMON_MODULES_AVAILABLE = True
except ImportError:
    print("⚠️ 공통 모듈을 찾을 수 없습니다. 기본 함수를 사용합니다.")
    COMMON_MODULES_AVAILABLE = False
    
    # 폴백: 기본 LLM 선택지
    LLM_CHOICES = {
        "1": ("gemma", "gemma4:e4b"),
        "2": ("qwen", "qwen3-vl:8b"),
        "3": ("llama", "llama3.2-vision"),
        "4": ("ministral", "ministral-3:14b"),
    }
    
    def list_images(folder):
        if not os.path.exists(folder):
            return []
        return sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg'))
        )
    
    def list_texts(folder):
        if not os.path.exists(folder):
            return []
        return sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith('.txt')
        )
    
    def write_text_file(path, content):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def sanitize_filename(text):
        import re
        if not text:
            return "unknown"
        text = re.sub(r'\([^)]*\)', '', text)
        text = re.sub(r'[^\w\-_\.]', '_', text)
        text = re.sub(r'_+', '_', text)
        text = text.strip('_')
        return text if text else "unknown"
    
    def sanitize_model_name_for_path(model_name):
        s = (model_name or "unknown").strip()
        for c in '\\/:*?"<>|':
            s = s.replace(c, "_")
        s = s.replace(":", "-")
        return s or "unknown"

    def unique_doc_filename_stem(doc_name, image_stem):
        dn = (doc_name or "").strip()
        ins = (image_stem or "").strip()
        if not dn:
            return ins or "unknown"
        if not ins:
            return dn or "unknown"
        if ins == dn:
            return dn
        if ins.startswith(dn + "_"):
            return ins
        return f"{dn}_{ins}"

    def short_llm_tag_for_filename(llm):
        """폴백: config_models.short_llm_tag_for_filename 과 동일 목적."""
        if not llm:
            return "unknown"
        import re as _re
        s = str(llm).strip().lower()
        s = _re.sub(r"\([^)]*\)", "", s)
        s = _re.sub(r"\s+", "_", s)
        s = _re.sub(r"_+", "_", s).strip("_")
        _keys = ("gemma", "qwen", "llama", "ministral")
        if s in _keys:
            return s
        first = s.split("_")[0]
        if first in _keys:
            return first
        for k in sorted(_keys, key=len, reverse=True):
            if s.startswith(k + "_"):
                return k
        return first if first else "unknown"

from classify_image_vlm import (  # noqa: E402
    load_convnext_model,
    process_folder_vision,
    predict_diagram_type,
    sanitize_model_name_for_path,
)

PROJECT_ROOT = str(CODE_ROOT)  # 2_CODE
# 배치 스크립트 산출물: 3_RESULT/batch_results (입력으로 받지 않음)
OUTPUT_ROOT = os.path.join(REPO_ROOT, "3_RESULT", "batch_results")


# ---------------------------------------------------------------------------
# 유틸리티 (공통 모듈 사용)
# ---------------------------------------------------------------------------

def prompt_path(label):
    while True:
        value = input(f"{label}: ").strip().strip('"').strip("'")
        if value:
            return os.path.abspath(value)
        print("경로를 입력해주세요.")


def prompt_llm():
    _qwen_vlm = LLM_CHOICES["2"][1]
    print(
        f"\nADR/PRD/TestPlan에 사용할 LLM을 선택하세요. "
        f"(이미지 분류 VLM은 qwen 고정: {_qwen_vlm})"
    )
    for k, (name, full) in LLM_CHOICES.items():
        print(f"  {k}. {name} ({full})")
    while True:
        choice = input("선택 (번호): ").strip()
        if choice in LLM_CHOICES:
            return LLM_CHOICES[choice]
        print("유효한 번호를 입력해주세요.")


def prompt_yes_no(label, default="y"):
    """사용자 Yes/No 입력 (기본값 지원)"""
    hint = "Y/n" if default.lower() == "y" else "y/N"
    value = input(f"{label} ({hint}): ").strip().lower()
    if not value:
        return default.lower() == "y"
    return value == "y"


# list_images, list_texts, sanitize_filename, write_md는 utils_common에서 import
write_md = write_text_file  # 별칭 유지 (하위 호환성)


def _gen_prd(prd_generator, adr_path):
    """구버전 generate_PRD.py(save_result_file 미지원)과 호환."""
    try:
        return prd_generator.generate_prd(adr_path, save_result_file=False)
    except TypeError:
        return prd_generator.generate_prd(adr_path)


def _gen_testplan(tp_generator, adr_path):
    """구버전 generate_testplan.py(save_result_file 미지원)과 호환."""
    try:
        return tp_generator.generate_test_plan(adr_path, save_result_file=False)
    except TypeError:
        return tp_generator.generate_test_plan(adr_path)


def _remove_spurious_adr_prd_testplan(doc_folder):
    """PRD/TestPlan 생성기가 _ADR 접미어 처리 오류로 만든 *_ADR_PRD.md, *_ADR_TestPlan.md 제거."""
    if not os.path.isdir(doc_folder):
        return
    for name in os.listdir(doc_folder):
        if name.endswith("_ADR_PRD.md") or name.endswith("_ADR_TestPlan.md"):
            try:
                os.remove(os.path.join(doc_folder, name))
            except OSError:
                pass


def _existing_output_md_ok(path):
    """폴더가 아닌 실제 파일이며, 비어 있지 않은 산출물 md인지 확인한다."""
    try:
        return os.path.isfile(path) and os.path.getsize(path) > 0
    except OSError:
        return False


# ---------------------------------------------------------------------------
# ConvNeXt 모델 로드 (app_vision과 동일: 프로젝트 루트 models/ 기준)
# ---------------------------------------------------------------------------

def load_convnext(project_root):
    """classify_image_vlm.load_convnext_model 과 동일 목적을 위해
    CWD와 무관하게 저장소 루트의 4_MODELS/convnext_best.pth 를 로드한다.
    모델 구성·가중치 로딩 로직은 app_vision과 완전히 동일."""
    from convnext_diagram_classifier import ConvNeXtDiagramClassifier

    model_path = os.path.join(project_root, "4_MODELS", "convnext_best.pth")
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"  디바이스: {device}")

    classifier = ConvNeXtDiagramClassifier(num_classes=2, device=device)
    classifier.build_model(pretrained=False, freeze_backbone=False)

    checkpoint = torch.load(model_path, map_location=device)
    classifier.model.load_state_dict(checkpoint["model_state_dict"])
    print("  ConvNeXt 모델 로드 완료")
    return classifier


# ---------------------------------------------------------------------------
# 시스템개념도 대표 1장 선택
# ---------------------------------------------------------------------------

def pick_best_concept_image(concept_dir, convnext_model):
    """1_시스템개념도 폴더에서 predict_diagram_type 결과의
    diagram_prob 가 가장 높은 이미지 1장을 반환한다."""
    images = list_images(concept_dir)
    if not images:
        return None

    candidates = []
    for img_path in images:
        result = predict_diagram_type(convnext_model, img_path)
        if not result:
            continue
        diagram_prob = float(result["probabilities"]["다이어그램"])
        candidates.append({
            "image_path": img_path,
            "image_name": os.path.basename(img_path),
            "diagram_prob": diagram_prob,
            "predicted_class": result["predicted_class"],
            "confidence": float(result["confidence"]),
        })

    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (-x["diagram_prob"], x["image_name"]))[0]


# ---------------------------------------------------------------------------
# 문서 생성 (app_vision generate_documents_for_image 과 동일 알고리즘)
# ---------------------------------------------------------------------------

def generate_documents(image_path, texts_folder, chroma_db_path,
                       llm_model, doc_name, doc_folder):
    """app_vision.py의 generate_documents_for_image와 동일한 호출 순서·인자로
    ADR → PRD → TestPlan 을 생성하고 결과 파일 경로를 반환한다.
    각 산출물 경로에 대해 기존 파일이 있고 내용이 비어 있지 않으면 해당 단계만 스킵한다."""
    image_name = os.path.basename(image_path)
    image_name_without_ext = os.path.splitext(image_name)[0]
    llm_safe = short_llm_tag_for_filename(llm_model)
    os.makedirs(doc_folder, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    file_stem = unique_doc_filename_stem(doc_name, image_name_without_ext)
    adr_file = os.path.join(doc_folder, f"{file_stem}_{llm_safe}_ADR.md")
    prd_file = os.path.join(doc_folder, f"{file_stem}_{llm_safe}_PRD.md")
    tp_file = os.path.join(doc_folder, f"{file_stem}_{llm_safe}_TestPlan.md")

    results = {"adr_file": None, "prd_file": None, "testplan_file": None}

    # ── 1. ADR (RAGSystem.process_image) ──
    if _existing_output_md_ok(adr_file):
        print(f"    ADR 스킵 (기존 파일): {os.path.basename(adr_file)}")
        results["adr_file"] = adr_file
    else:
        print(f"    ADR 생성 중... ({image_name})")
        rag_system = RAGSystem(chroma_db_path)
        adr_start = time.time()
        adr_result = rag_system.process_image(
            image_path,
            texts_folder,
            llm_model=llm_model,
            llm_display=llm_model.capitalize(),
            embedding_display=f"HuggingFace ({RAG_EMBEDDING_DISPLAY_NAME})",
            result_dir=None,
        )
        adr_time = time.time() - adr_start

        if not adr_result or adr_result.startswith("이미지 파일을 읽을 수 없습니다"):
            raise RuntimeError(f"ADR 생성 실패: {adr_result}")

        adr_content = (
            f"# ADR 생성 결과 (LLM: {llm_model})\n\n"
            f"**이미지:** {image_name}\n"
            f"**생성일시:** {now_str}\n"
            f"**소요 시간:** {adr_time:.2f}초 ({adr_time/60:.2f}분)\n\n"
            f"---\n\n{adr_result}"
        )
        write_md(adr_file, adr_content)
        results["adr_file"] = adr_file
        print(f"    ADR 저장 완료 ({adr_time:.1f}s)")

    if not _existing_output_md_ok(adr_file):
        raise RuntimeError("ADR 파일이 없습니다. PRD/TestPlan을 진행할 수 없습니다.")

    # ── 2. PRD (PRDGenerator.generate_prd) ──
    if _existing_output_md_ok(prd_file):
        print(f"    PRD 스킵 (기존 파일): {os.path.basename(prd_file)}")
        results["prd_file"] = prd_file
    else:
        print(f"    PRD 생성 중... ({image_name})")
        prd_start = time.time()
        prd_generator = PRDGenerator(llm_model=llm_model)
        prd_result = _gen_prd(prd_generator, adr_file)
        prd_time = time.time() - prd_start

        if not isinstance(prd_result, str):
            prd_result = getattr(prd_result, "content", str(prd_result)) if prd_result is not None else ""
        if not prd_result or prd_result.startswith("파일을 읽을 수 없습니다"):
            raise RuntimeError("PRD 생성 실패: ADR 읽기 실패 또는 LLM이 빈 응답을 반환했습니다.")
        if prd_result.startswith("PRD 생성 중 오류"):
            raise RuntimeError(f"PRD 생성 실패: {prd_result}")

        prd_content = (
            f"# PRD 생성 결과 (LLM: {llm_model})\n\n"
            f"**이미지:** {image_name}\n"
            f"**생성일시:** {now_str}\n"
            f"**소요 시간:** {prd_time:.2f}초 ({prd_time/60:.2f}분)\n\n"
            f"---\n\n{prd_result}"
        )
        write_md(prd_file, prd_content)
        results["prd_file"] = prd_file
        print(f"    PRD 저장 완료 ({prd_time:.1f}s)")

    # ── 3. TestPlan (TestPlanGenerator.generate_test_plan) ──
    if _existing_output_md_ok(tp_file):
        print(f"    TestPlan 스킵 (기존 파일): {os.path.basename(tp_file)}")
        results["testplan_file"] = tp_file
    else:
        print(f"    TestPlan 생성 중... ({image_name})")
        tp_start = time.time()
        tp_generator = TestPlanGenerator(llm_model=llm_model)
        tp_result = _gen_testplan(tp_generator, adr_file)
        tp_time = time.time() - tp_start

        if not isinstance(tp_result, str):
            tp_result = getattr(tp_result, "content", str(tp_result)) if tp_result is not None else ""
        if not tp_result or tp_result.startswith("파일을 읽을 수 없습니다"):
            raise RuntimeError("TestPlan 생성 실패: ADR 읽기 실패 또는 LLM이 빈 응답을 반환했습니다.")
        if tp_result.startswith("Test Plan 생성 중 오류"):
            raise RuntimeError(f"TestPlan 생성 실패: {tp_result}")

        tp_content = (
            f"# TestPlan 생성 결과 (LLM: {llm_model})\n\n"
            f"**이미지:** {image_name}\n"
            f"**생성일시:** {now_str}\n"
            f"**소요 시간:** {tp_time:.2f}초 ({tp_time/60:.2f}분)\n\n"
            f"---\n\n{tp_result}"
        )
        write_md(tp_file, tp_content)
        results["testplan_file"] = tp_file
        print(f"    TestPlan 저장 완료 ({tp_time:.1f}s)")

    # 구버전 생성기·접미어 버그로 남는 잘못된 파일명 정리 (정상 3종만 유지)
    _remove_spurious_adr_prd_testplan(doc_folder)

    return results


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("  배치 PDF → 문서 생성 (v2, app_vision 동일 알고리즘)")
    print("=" * 70)

    input_pdf_dir = prompt_path("PDF 폴더 경로")
    output_root = OUTPUT_ROOT
    llm_model, llm_display = prompt_llm()
    _, classification_llm_display = LLM_CHOICES["2"]  # 이미지 분류 VLM: qwen 고정

    chroma_db_path = os.path.join(REPO_ROOT, "5_DB", "chroma_db_hf")

    if not os.path.isdir(input_pdf_dir):
        print(f"[오류] PDF 폴더가 없습니다: {input_pdf_dir}")
        return
    if not os.path.exists(chroma_db_path):
        print(f"[오류] Chroma DB 경로가 없습니다: {chroma_db_path}")
        return

    pdf_files = sorted(f for f in os.listdir(input_pdf_dir) if f.lower().endswith(".pdf"))
    if not pdf_files:
        print(f"[오류] PDF 파일이 없습니다: {input_pdf_dir}")
        return

    # 출력은 문서명(pdf_stem) 폴더가 먼저: <output_root>/<pdf_stem>/extracted_images|...
    os.makedirs(output_root, exist_ok=True)

    print(f"\n  PDF 폴더 : {input_pdf_dir}")
    print(f"  출력 폴더 : {output_root}")
    print(f"  이미지 분류 VLM: {classification_llm_display} (qwen 고정)")
    print(f"  문서 생성 LLM : {llm_display} ({llm_model})")
    print(f"  Chroma DB: {chroma_db_path}")
    print(f"  PDF 개수  : {len(pdf_files)}")

    if not prompt_yes_no("\n이대로 시작할까요?"):
        print("취소되었습니다.")
        return

    # ConvNeXt 모델 1회 로딩
    print("\nConvNeXt 모델 로딩 중...")
    convnext_model = load_convnext(REPO_ROOT)

    started = time.time()
    success = 0
    skipped = 0
    failed = 0

    for idx, pdf_file in enumerate(pdf_files, 1):
        pdf_path = os.path.join(input_pdf_dir, pdf_file)
        pdf_name = os.path.splitext(pdf_file)[0]
        print(f"\n[{idx}/{len(pdf_files)}] {pdf_file}")

        doc_root = os.path.join(output_root, pdf_name)
        extracted_images_root = os.path.join(doc_root, "extracted_images")
        extracted_texts_root = os.path.join(doc_root, "extracted_texts")
        classified_images_root = os.path.join(doc_root, "classified_images")
        generated_docs_root = os.path.join(doc_root, "generated_docs")
        logs_root = os.path.join(doc_root, "logs")
        for d in (doc_root, extracted_images_root, extracted_texts_root,
                  classified_images_root, generated_docs_root, logs_root):
            os.makedirs(d, exist_ok=True)

        # 수정: 문서명 중복 제거 (extracted_images 바로 하위에 이미지 저장)
        doc_image_dir = extracted_images_root  # pdf_name 제거
        doc_text_dir = extracted_texts_root    # pdf_name 제거
        doc_doc_dir = generated_docs_root
        log_path = os.path.join(logs_root, f"{pdf_name}_log.txt")

        try:
            # ── 1) 이미지 추출 (app_vision 동일: extract_images_from_pdf) ──
            os.makedirs(doc_image_dir, exist_ok=True)
            existing_imgs = list_images(doc_image_dir)
            if existing_imgs:
                print(f"  이미지 추출 스킵 (기존 {len(existing_imgs)}개)")
            else:
                img_paths = extract_images_from_pdf(pdf_path, doc_image_dir)
                print(f"  이미지 추출: {len(img_paths)}개")

            # ── 2) 텍스트 추출 (app_vision 동일: extract_text_from_pdf) ──
            os.makedirs(doc_text_dir, exist_ok=True)
            existing_txts = list_texts(doc_text_dir)
            if existing_txts:
                print(f"  텍스트 추출 스킵 (기존 {len(existing_txts)}개)")
            else:
                extract_text_from_pdf(pdf_path, output_dir=doc_text_dir)
                txt_count = len(list_texts(doc_text_dir))
                print(f"  텍스트 추출: {txt_count}개")

            # ── 3) 이미지 분류 (VLM은 qwen 고정, 문서 생성 LLM과 별도) ──
            print(f"  이미지 분류 Vision LLM: {classification_llm_display} (qwen 고정)")
            process_folder_vision(
                extracted_images_root,  # extracted_images 폴더 직접 전달
                convnext_model,
                model_name=classification_llm_display,
                selected_doc_name=None,  # 하위 폴더 없으므로 None
            )

            # 단일 문서: <doc_root>/classified_images/<LLM>/1_시스템개념도/…
            # 수정: 문서명 중복 제거
            concept_dir = os.path.join(
                classified_images_root,
                sanitize_model_name_for_path(classification_llm_display),
                "1_시스템개념도",
            )
            if not os.path.exists(concept_dir) or not list_images(concept_dir):
                msg = "시스템개념도 후보가 없어 스킵"
                print(f"  {msg}")
                write_md(log_path, f"pdf: {pdf_file}\nskip: {msg}\n")
                skipped += 1
                continue

            # ── 4) 대표 이미지 1장 선택 ──
            best = pick_best_concept_image(concept_dir, convnext_model)
            if not best:
                msg = "다이어그램 후보 점수가 없어 스킵"
                print(f"  {msg}")
                write_md(log_path, f"pdf: {pdf_file}\nskip: {msg}\n")
                skipped += 1
                continue

            print(f"  대표 이미지: {best['image_name']}  "
                  f"(diagram_prob={best['diagram_prob']:.4f})")

            # ── 5) 문서 생성 (app_vision 동일 알고리즘) ──
            doc_results = generate_documents(
                best["image_path"],
                doc_text_dir,
                chroma_db_path,
                llm_model,
                pdf_name,
                doc_doc_dir,
            )

            log_lines = [
                f"pdf: {pdf_file}",
                f"selected_image: {best['image_name']}",
                f"diagram_prob: {best['diagram_prob']:.6f}",
                f"predicted_class: {best['predicted_class']}",
                f"confidence: {best['confidence']:.6f}",
                f"adr: {doc_results['adr_file']}",
                f"prd: {doc_results['prd_file']}",
                f"testplan: {doc_results['testplan_file']}",
            ]
            write_md(log_path, "\n".join(log_lines) + "\n")

            print("  문서 생성 완료 (ADR / PRD / TestPlan)")
            success += 1

        except Exception as e:
            failed += 1
            print(f"  실패: {e}")
            traceback.print_exc()
            write_md(log_path, f"pdf: {pdf_file}\nerror: {e}\n")

    elapsed = time.time() - started
    print("\n" + "=" * 70)
    print("  처리 완료")
    print("=" * 70)
    print(f"  총 PDF  : {len(pdf_files)}")
    print(f"  성공    : {success}")
    print(f"  스킵    : {skipped}")
    print(f"  실패    : {failed}")
    print(f"  소요시간: {elapsed:.1f}초 ({elapsed/60:.1f}분)")
    print(f"  출력루트: {output_root}")
    print("=" * 70)


if __name__ == "__main__":
    main()
