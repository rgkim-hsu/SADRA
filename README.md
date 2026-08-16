# An Empirical Analysis of Multi-Reference Bias in Open-Source Multimodal LLM-based ADR Generation for Smartfarm Systems

> 스마트팜 시스템을 위한 오픈소스 멀티모달 LLM 기반 ADR 생성 결과의다중 레퍼런스 평가 변동성 및 계열 유사성 편향 실증 분석
> Yong-gyu Kim 

## Repository Structure

| File | Description |
|------|-------------|
| `calculate_similarity.py` | 12개 유사도 메트릭 산출 (어휘6/의미3/구조3) |
| `convnext_diagram_classifier.py` | ConvNeXt-Base 다이어그램 분류기 |
| `statistical_analysis.py` | 논문 전체 통계 분석 재현 (§4.1–§4.5) |
| `requirements.txt` | Python 의존성 패키지 |

## Reproduction
1. 통계 재현 (Python)
   pip install -r requirements.txt
   python statistical_analysis.py ./data/
2. 통계 재현 (스프레드시트, Python 불필요)
   docs/KIIT_Stats_Workbook_통계재현.xlsx 를 연다.
   논문에 인쇄된 82개 통계량이 셀 수식으로 계산되어 '14_논문대조' 시트에서 논문 값과 자동 대조한다.

## Key Results

- Reference selection (η²=0.282) outweighs the evaluated model (η²=0.246) as a single variance source
- Same-family advantage (+0.053 raw, rank-biserial r=+0.412) shrinks to +0.007–+0.028 after removing reference leniency
- Post-hoc signals explain 67% (R²=0.673, LOOCV R²=0.604); a reference-free 3-signal model reaches R²=0.760, LOOCV R²=0.688

## Citation
Y. Kim and K. H. Rho, "스마트팜 시스템을 위한 오픈소스 멀티모달 LLM 기반 ADR 생성결과의 다중 레퍼런스 평가 변동성 및 계열 유사성 편향 실증 분석,"
