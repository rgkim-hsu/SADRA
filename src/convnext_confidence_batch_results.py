"""
batch_results 하위 각 문서 폴더의 extracted_images 에서 ConvNeXt(다이어그램 vs 일반이미지)
분류 확률·신뢰도를 수집해 CSV로 저장합니다.

실행 (저장소 루트 기준 2_CODE 에서):
  python scripts/convnext_confidence_batch_results.py

모델: 4_MODELS/convnext_best.pth (classify_image_vlm.load_convnext_model 과 동일)
전처리: classify_image_vlm.predict_diagram_type 과 동일 (224 resize, ImageNet normalize)
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import torch
import torchvision.transforms as transforms
from PIL import Image
from tqdm import tqdm

# 2_CODE 경로 (CWD 무관)
_CODE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CODE_ROOT / "core"))
from code_paths import setup_project_paths

REPO_ROOT, CODE_ROOT = setup_project_paths(include_classification_extras=True)

from convnext_diagram_classifier import ConvNeXtDiagramClassifier

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, Exception):
    pass

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def load_convnext_model():
    """classify_image_vlm.load_convnext_model 과 동일."""
    model_path = REPO_ROOT / "4_MODELS" / "convnext_best.pth"
    if not model_path.is_file():
        raise FileNotFoundError(f"모델 파일이 없습니다: {model_path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    classifier = ConvNeXtDiagramClassifier(num_classes=2, device=device)
    classifier.build_model(pretrained=False, freeze_backbone=False)
    checkpoint = torch.load(model_path, map_location=device)
    classifier.model.load_state_dict(checkpoint["model_state_dict"])
    return classifier


def predict_probs(convnext_model: ConvNeXtDiagramClassifier, image_path: Path) -> dict[str, Any]:
    """softmax 확률 및 argmax 신뢰도. 클래스 0=다이어그램, 1=일반이미지."""
    image = Image.open(image_path).convert("RGB")
    transform = transforms.Compose(
        [
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ]
    )
    image_tensor = transform(image).unsqueeze(0)
    device = next(convnext_model.model.parameters()).device
    image_tensor = image_tensor.to(device)

    convnext_model.model.eval()
    with torch.no_grad():
        output = convnext_model.model(image_tensor)
        probabilities = torch.softmax(output, dim=1)
        predicted_class = torch.argmax(output, dim=1).item()
        confidence = probabilities[0][predicted_class].item()

    p_diag = probabilities[0][0].item()
    p_gen = probabilities[0][1].item()
    class_names_ko = ["다이어그램", "일반이미지"]
    class_names_en = ["diagram", "general"]

    return {
        "predicted_class_idx": predicted_class,
        "predicted_class_ko": class_names_ko[predicted_class],
        "predicted_class_en": class_names_en[predicted_class],
        "confidence": confidence,
        "prob_diagram": p_diag,
        "prob_general": p_gen,
    }


def iter_image_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            yield p


def find_extracted_images_dirs(document_dir: Path) -> list[Path]:
    """문서 폴더 아래 이름이 extracted_images 인 모든 디렉터리."""
    found: list[Path] = []
    for p in document_dir.rglob("*"):
        if p.is_dir() and p.name == "extracted_images":
            found.append(p.resolve())
    return sorted(set(found), key=lambda x: str(x))


def main() -> None:
    parser = argparse.ArgumentParser(description="ConvNeXt 신뢰도 배치 수집 (batch_results / extracted_images)")
    default_batch = REPO_ROOT / "3_RESULT" / "batch_results"
    parser.add_argument(
        "--batch-root",
        type=Path,
        default=default_batch,
        help=f"batch_results 루트 (기본: {default_batch})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="출력 CSV 경로 (기본: 3_RESULT/convnext_confidence_YYYYMMDD_HHMMSS.csv)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="디버그용: 처리할 이미지 수 상한 (0이면 전체)",
    )
    args = parser.parse_args()

    batch_root: Path = args.batch_root.resolve()
    if not batch_root.is_dir():
        print(f"오류: batch_root 가 폴더가 아닙니다: {batch_root}")
        sys.exit(1)

    out_path = args.output
    if out_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = REPO_ROOT / "3_RESULT" / f"convnext_confidence_{ts}.csv"
    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"모델 로드 중… (device: {'cuda' if torch.cuda.is_available() else 'cpu'})")
    model = load_convnext_model()

    doc_dirs = sorted([p for p in batch_root.iterdir() if p.is_dir()])
    rows: list[dict[str, Any]] = []
    total_written = 0

    for doc_dir in tqdm(doc_dirs, desc="문서 폴더"):
        doc_name = doc_dir.name
        extracted_roots = find_extracted_images_dirs(doc_dir)
        if not extracted_roots:
            continue

        for ei_root in extracted_roots:
            for img_path in iter_image_files(ei_root):
                rel_in_extracted = img_path.relative_to(ei_root)
                row_base = {
                    "document_folder": doc_name,
                    "extracted_images_root": str(ei_root),
                    "image_relative_path": str(rel_in_extracted).replace("\\", "/"),
                    "image_path": str(img_path.resolve()),
                }
                try:
                    pred = predict_probs(model, img_path)
                    row = {
                        **row_base,
                        "predicted_class_idx": pred["predicted_class_idx"],
                        "predicted_class_ko": pred["predicted_class_ko"],
                        "predicted_class_en": pred["predicted_class_en"],
                        "confidence": f"{pred['confidence']:.6f}",
                        "prob_diagram": f"{pred['prob_diagram']:.6f}",
                        "prob_general": f"{pred['prob_general']:.6f}",
                        "error": "",
                    }
                except Exception as e:
                    row = {
                        **row_base,
                        "predicted_class_idx": "",
                        "predicted_class_ko": "",
                        "predicted_class_en": "",
                        "confidence": "",
                        "prob_diagram": "",
                        "prob_general": "",
                        "error": str(e),
                    }
                rows.append(row)
                total_written += 1
                if args.limit > 0 and total_written >= args.limit:
                    break
            if args.limit > 0 and total_written >= args.limit:
                break
        if args.limit > 0 and total_written >= args.limit:
            break

    fieldnames = [
        "document_folder",
        "extracted_images_root",
        "image_relative_path",
        "image_path",
        "predicted_class_idx",
        "predicted_class_ko",
        "predicted_class_en",
        "confidence",
        "prob_diagram",
        "prob_general",
        "error",
    ]
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"완료: {len(rows)}행 → {out_path}")


if __name__ == "__main__":
    main()
