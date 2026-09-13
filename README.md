# Multi-Reference Bias Analysis in LLM-based ADR Generation for Smart Farm Systems

> 스마트팜 시스템을 위한 오픈소스 LLM 기반 ADR 생성 결과의 다중 레퍼런스 편향 실증 분석

This repository contains the data, analysis code, and a fully formula-driven reproduction
workbook for the paper. All statistics reported in the paper can be recomputed cell by cell.

<img width="567" height="166" alt="image" src="https://github.com/user-attachments/assets/890cb190-05a7-4e57-84d0-2fa442b3286f" />

## Repository Structure

| Path | Description |
| --- | --- |
| `ADRs/` | Source diagrams and generated ADRs — 65 documents × 7 models (5 reference, 3 open-source local) |
| `data/similarity_*_as_reference.xlsx` | Per-reference similarity scores for all 975 evaluation pairs |
| `data/statistical_analysis_results.xlsx` | Aggregated analysis outputs |
| `data/figures/` | Generated figures |
| `docs/KIIT_Stats_Workbook_통계재현.xlsx` | **Reproduction workbook** — every reported statistic as a live spreadsheet formula |
| `docs/IoT_SmartFarm_Standards.txt` | Domain standards corpus used for RAG indexing |
| `prompts/adr_generation_template.md` | Single prompt template used for all models |
| `src/calculate_similarity.py` | 12 similarity metrics (lexical / semantic / structural) |
| `src/statistical_analysis.py` | Full statistical reproduction (§4.1–§4.5) |
| `src/convnext_diagram_classifier.py` | ConvNeXt-Base diagram classifier |
| `src/batch_pdf_to_doc.py` | Document preprocessing |
| `requirements.txt` | Python dependencies |

## Quick Start

```bash
pip install -r requirements.txt
python src/statistical_analysis.py ./data/
```

Environment: Python 3.11, scipy 1.11, statsmodels 0.14, pingouin 0.5.

## Reproduction Workbook

`docs/KIIT_Stats_Workbook_통계재현.xlsx` carries the raw 975 evaluation pairs and recomputes
every printed statistic through spreadsheet formulas — sum-of-squares decomposition, variance
components, rank-based tests, double-centered residuals, regression, and LOOCV.

| Sheet | Content |
| --- | --- |
| `01_원자료` | 975 evaluation pairs (65 documents × 3 local models × 5 references) |
| `03_가중치민감도` · `03B_시나리오점수` | Overall Score weight sensitivity, 6 scenarios |
| `05_이원분산분석` · `05B_가정검정` | Variance decomposition and assumption checks |
| `08_KW_Holm` | Independent-sample tests (retained for comparison) |
| `08B_대응표본Wilcoxon` | **Friedman + paired Wilcoxon over 65 document blocks** |
| `10_계열편향` · `10B_문서단위잔차` | Family bias before and after leniency control |
| `12_사후회귀` · `13_레퍼런스프리` | Post-hoc signal regression, reference-free model |
| `14_논문대조` | Side-by-side check against the printed values |

## Key Results

- **Reference selection explains more score variance than the evaluated model**
  (η² = 0.282 vs 0.246; document-level random effect ICC = 0.269).
- **Family-similarity bias is real but overestimated by raw scores.** For the Google family the
  raw gap is +0.0890 while the double-centered residual is +0.0276 — about 3.2× smaller.
  The LMM contrast confirms the effect (+0.0288, SE 0.0040, p < .001).
- **A reference-free signal works.** A three-signal model built only from inter-model consensus
  and output length reaches R² = 0.760 (LOOCV 0.688), above the reference-based two-signal
  model (R² = 0.673, LOOCV 0.604).
- **Structural metrics are sensitive to Markdown dialects.** Supporting both ATX and Setext
  headings reduces zero-truncated document similarity from 60.2% to 8.4% and raises the mean
  from 0.254 to 0.478.

Model comparison uses Friedman and paired Wilcoxon signed-rank tests over 65 document blocks;
the 975 pairs are repeated measurements, not independent samples.

## Data Note

Document identifiers are de-identified. The mapping between identifiers and the original
patent/report sources is not distributed.

## Citation

```
(To be completed on acceptance)
```

## License

MIT
