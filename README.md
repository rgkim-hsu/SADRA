# Multi-Reference Bias Analysis in LLM-based ADR Generation for Smart Farm Systems

> 스마트팜 시스템을 위한 오픈소스 멀티모달 LLM 기반 ADR 생성 결과의 다중 레퍼런스 편향 실증 분석
> Yong-gyu Kim 

## Repository Structure

| File | Description |
|------|-------------|
| `calculate_similarity.py` | 11개 유사도 메트릭 산출 (어휘/의미/구조) |
| `convnext_diagram_classifier.py` | ConvNeXt-Base 다이어그램 분류기 |
| `statistical_analysis.py` | 논문 전체 통계 분석 재현 (§4.1–§4.6) |
| `requirements.txt` | Python 의존성 패키지 |

## Quick Start

```bash
pip install -r requirements.txt
python statistical_analysis.py ./data/
```

## Key Results

- Reference selection (η²=0.440) dominates evaluation scores
- Family bias is asymmetric (rank-biserial r=+0.427, Cohen's d=+0.835)
- Post-hoc output signals explain 86% of variance (R²=0.862)

## Citation
 
