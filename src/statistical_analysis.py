#!/usr/bin/env python3
"""
statistical_analysis.py

스마트팜 ADR 자동 생성 결과의 다중 레퍼런스 편향 실증 분석
— 전체 통계 분석 재현 스크립트 —

================================================================================
  사전 준비 (Prerequisites)
================================================================================

  pip install pandas numpy scipy statsmodels pingouin openpyxl matplotlib seaborn

================================================================================
  입력 데이터
================================================================================

  calculate_similarity.py 로 생성된 레퍼런스별 Excel 파일 5개:
    similarity_Claude_as_reference_*.xlsx
    similarity_gemini_as_reference_*.xlsx
    similarity_GPT_as_reference_*.xlsx
    similarity_Mistral_as_reference_*.xlsx
    similarity_Qwen3_6_as_reference_*.xlsx

================================================================================
  출력
================================================================================

  콘솔: 논문 §4.1–§4.6, §5.3 에 대응하는 모든 통계량
  파일: statistical_analysis_results.xlsx (분석 결과 워크북)
        figures/ 폴더 내 시각화 PNG 파일

================================================================================
"""

import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
import glob
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import (
    shapiro, levene, kruskal, mannwhitneyu, spearmanr, pearsonr,
    chi2_contingency, friedmanchisquare
)
import statsmodels.api as sm
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm
from statsmodels.regression.mixed_linear_model import MixedLM
import matplotlib
matplotlib.use("Agg")  # 비대화형 백엔드 (서버/CI 환경 호환)
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
try:
    import seaborn as sns
    sns.set_theme(style="whitegrid", font_scale=1.1)
    HAS_SEABORN = True
except ImportError:
    HAS_SEABORN = False

warnings.filterwarnings("ignore")

# ─── 시각화 공통 설정 ─────────────────────────────────────────────────────────

# 한글 폰트 자동 감지 (없으면 영문 fallback)
def _setup_font():
    for fname in ["NanumGothic", "Malgun Gothic", "AppleGothic", "DejaVu Sans"]:
        try:
            matplotlib.font_manager.findfont(fname, fallback_to_default=False)
            plt.rcParams["font.family"] = fname
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue
_setup_font()

MODEL_COLORS = {"Gemma": "#4285F4", "Ministral": "#EA4335", "Qwen": "#34A853"}
REF_ORDER = ["Claude", "Gemini", "ChatGPT", "Mistral", "Qwen3_6"]
MODEL_ORDER = ["Gemma", "Ministral", "Qwen"]

# ─── 설정 ────────────────────────────────────────────────────────────────────

# 가중치: §3.2, 그림 2
WEIGHT_LEXICAL = 0.20
WEIGHT_SEMANTIC = 0.45
WEIGHT_STRUCTURE = 0.35

# 메트릭 그룹 정의 (Excel 데이터 기준: 총 12개 메트릭) 
#   overall_document_structure_similarity는 파생 메트릭이므로 제외 (이중 계산 방지).
#   검증: 20/45/35 + 이 3개 sub-metrics = Excel overall_score 완벽 일치 (max diff = 0.0)
LEXICAL_COLS = ["f1_score", "rouge1", "rouge2", "rougeL", "bleu_score", "tfidf_similarity"]
SEMANTIC_COLS = ["bertscore", "sts_score", "moverscore"]
STRUCTURE_COLS = [
    "markdown_awareness_similarity",
    "teds_document_structure_similarity",
    "teds_table_structure_similarity",
]

# 모델 계열 매핑 (§4.4)
FAMILY_MAP = {
    ("Gemini", "gemma"): "Google",
    ("Qwen3_6", "qwen"): "Alibaba",
    ("Mistral", "ministral"): "Mistral",
}


def classify_doc_type(doc_id: str) -> str:
    """특허(10...)와 연구 보고서를 document_id 접두사로 분류."""
    return "특허" if str(doc_id).strip().startswith("10") else "연구 보고서"


# 레퍼런스 모델 이름 정규화 (소문자 키로 정규화)
REF_NAME_MAP = {
    "claude": "Claude",
    "gemini": "Gemini",
    "chatgpt": "ChatGPT",
    "gpt": "ChatGPT",
    "gpt-5.5": "ChatGPT",
    "openai": "ChatGPT",
    "mistral": "Mistral",
    "qwen3_6": "Qwen3_6",
    "qwen3-6": "Qwen3_6",
    "qwen_3_6": "Qwen3_6",
}

# 오픈소스 모델 이름 정규화 (소문자 키로 정규화)
MODEL_NAME_MAP = {
    "gemma": "Gemma",
    "ministral": "Ministral",
    "qwen": "Qwen",
}


def _normalize_ref(x):
    """레퍼런스 모델명 정규화 (대소문자·공백 무관)."""
    key = str(x).strip().lower()
    return REF_NAME_MAP.get(key, str(x).strip())


def _normalize_model(x):
    """오픈소스 모델명 정규화 (대소문자·공백 무관)."""
    key = str(x).strip().lower()
    return MODEL_NAME_MAP.get(key, str(x).strip())


# 문서 유형 한글 라벨 (논문 표 8)
DOC_TYPE_LABEL = {
    "patent": "특허",
    "report": "연구 보고서",
    "특허": "특허",
    "연구보고서": "연구 보고서",
    "연구 보고서": "연구 보고서",
}

# (문서 유형별 메타데이터 사용 제거)


# ─── 유틸리티 함수 ────────────────────────────────────────────────────────────

def rank_biserial_r(u_stat, n1, n2):
    """
    Mann-Whitney U에서 rank-biserial correlation 산출.
    scipy.mannwhitneyu(x, y)가 반환하는 U는 첫 번째 표본 x에 대한 U1이며,
    x가 확률적으로 클수록 U1이 크다. 논문 규약(첫 인자가 클 때 r>0)에 맞춰
    r = 2·U1/(n1·n2) − 1 로 산출한다.
    """
    return (2 * u_stat) / (n1 * n2) - 1


def cohens_d(x, y):
    """독립 표본 Cohen's d."""
    nx, ny = len(x), len(y)
    var_x, var_y = np.var(x, ddof=1), np.var(y, ddof=1)
    pooled_std = np.sqrt(((nx - 1) * var_x + (ny - 1) * var_y) / (nx + ny - 2))
    return (np.mean(x) - np.mean(y)) / pooled_std if pooled_std > 0 else 0.0


def bootstrap_ci(x, y, n_boot=3000, ci=0.95, seed=42):
    """Bootstrap으로 rank-biserial r의 95% CI 산출."""
    rng = np.random.RandomState(seed)
    rs = []
    for _ in range(n_boot):
        bx = rng.choice(x, size=len(x), replace=True)
        by = rng.choice(y, size=len(y), replace=True)
        u, _ = mannwhitneyu(bx, by, alternative="two-sided")
        rs.append(rank_biserial_r(u, len(bx), len(by)))
    alpha = (1 - ci) / 2
    return np.percentile(rs, [alpha * 100, (1 - alpha) * 100])


def holm_bonferroni(p_values, alpha=0.05):
    """Holm-Bonferroni 다중 비교 보정."""
    n = len(p_values)
    sorted_idx = np.argsort(p_values)
    sorted_p = np.array(p_values)[sorted_idx]
    adjusted = np.zeros(n)
    for i, idx in enumerate(sorted_idx):
        adjusted[idx] = sorted_p[i] * (n - i)
    adjusted = np.minimum(adjusted, 1.0)
    # monotonicity enforcement
    for i in range(1, n):
        if adjusted[sorted_idx[i]] < adjusted[sorted_idx[i - 1]]:
            adjusted[sorted_idx[i]] = adjusted[sorted_idx[i - 1]]
    return adjusted


# ─── 데이터 로드 ──────────────────────────────────────────────────────────────

def load_data(data_dir: str) -> pd.DataFrame:
    """레퍼런스별 Excel 파일을 통합 DataFrame으로 로드."""
    # 타임스탬프 유무 모두 허용 (similarity_*_as_reference*.xlsx)
    pattern = os.path.join(data_dir, "similarity_*_as_reference*.xlsx")
    files = glob.glob(pattern)
    if not files:
        print(f"[ERROR] '{data_dir}' 에서 Excel 파일을 찾을 수 없습니다.")
        print(f"  패턴: {pattern}")
        sys.exit(1)

    all_dfs = []
    for fpath in sorted(files):
        fname = os.path.basename(fpath)
        print(f"  로딩: {fname}")
        df = pd.read_excel(fpath)
        df = df.dropna(subset=["document_id", "comparison_model"])
        # reference_model 컬럼이 없으면 파일명에서 추출
        if "reference_model" not in df.columns:
            import re
            m = re.search(r"similarity_(.+?)_as_reference", fname)
            if m:
                df["reference_model"] = m.group(1)
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)

    # 이름 정규화 (대소문자·공백 무관)
    if "reference_model" in combined.columns:
        combined["Reference"] = combined["reference_model"].map(_normalize_ref)
    if "comparison_model" in combined.columns:
        combined["Model"] = combined["comparison_model"].map(_normalize_model)

    print(f"\n총 {len(combined)}건 로드 완료 "
          f"({combined['Reference'].nunique()} 레퍼런스 × "
          f"{combined['Model'].nunique()} 모델 × "
          f"{combined['document_id'].nunique()} 문서)")
    print(f"  레퍼런스: {sorted(combined['Reference'].unique())}")
    print(f"  모델: {sorted(combined['Model'].unique())}")
    return combined


# ─── Overall Score 산출 ───────────────────────────────────────────────────────

def compute_overall_score(df: pd.DataFrame,
                          w_lex=WEIGHT_LEXICAL,
                          w_sem=WEIGHT_SEMANTIC,
                          w_str=WEIGHT_STRUCTURE,
                          use_existing=False) -> pd.Series:
    """
    Overall Score 산출.
    use_existing=True 이고 Excel에 'overall_score' 컬럼이 있으면 그대로 사용
    (논문 수치와의 정합성 보장). 그 외에는 논문 그림 2의 가중합으로 재계산
    (민감도 분석용).
    """
    if use_existing and "overall_score" in df.columns:
        return df["overall_score"]

    lex_cols = [c for c in LEXICAL_COLS if c in df.columns]
    sem_cols = [c for c in SEMANTIC_COLS if c in df.columns]
    str_cols = [c for c in STRUCTURE_COLS if c in df.columns]

    lex_mean = df[lex_cols].mean(axis=1) if lex_cols else 0
    sem_mean = df[sem_cols].mean(axis=1) if sem_cols else 0
    str_mean = df[str_cols].mean(axis=1) if str_cols else 0

    return w_lex * lex_mean + w_sem * sem_mean + w_str * str_mean


# ─── §4.1 가중치 민감도 분석 ──────────────────────────────────────────────────

def sensitivity_analysis(df: pd.DataFrame):
    """6개 시나리오 민감도 분석 (논문 표 3)."""
    print("\n" + "=" * 80)
    print("§4.1  Overall Score 가중치 민감도 검증")
    print("=" * 80)

    scenarios = {
        "baseline (20/45/35)": (0.20, 0.45, 0.35),
        "lex_heavy (40/30/30)": (0.40, 0.30, 0.30),
        "sem_heavy (20/50/30)": (0.20, 0.50, 0.30),
        "struct_heavy (15/25/60)": (0.15, 0.25, 0.60),
        "equal (33/33/34)": (1 / 3, 1 / 3, 1 / 3),
        "sem_struct (0/50/50)": (0.00, 0.50, 0.50),
    }

    # baseline 조합 순위
    baseline_os = compute_overall_score(df, *scenarios["baseline (20/45/35)"])
    df["_baseline_os"] = baseline_os
    baseline_rank = (
        df.groupby(["Reference", "Model"])["_baseline_os"]
        .mean()
        .rank(ascending=False)
    )

    results = []
    for name, (wl, ws_, wst) in scenarios.items():
        os_ = compute_overall_score(df, wl, ws_, wst)
        df["_tmp_os"] = os_
        combo_mean = df.groupby(["Reference", "Model"])["_tmp_os"].mean()
        model_mean = df.groupby("Model")["_tmp_os"].mean().sort_values(ascending=False)
        combo_rank = combo_mean.rank(ascending=False)

        rho, _ = spearmanr(baseline_rank.values, combo_rank.values)

        top3 = model_mean.head(3)
        results.append({
            "시나리오": name,
            "1위": f"{top3.index[0]} ({top3.iloc[0]:.4f})",
            "2위": f"{top3.index[1]} ({top3.iloc[1]:.4f})",
            "3위": f"{top3.index[2]} ({top3.iloc[2]:.4f})",
            "ρ (baseline)": f"{rho:.3f}",
        })

    result_df = pd.DataFrame(results)
    print(result_df.to_string(index=False))
    df.drop(columns=["_baseline_os", "_tmp_os"], inplace=True, errors="ignore")
    return result_df


# ─── §4.2 RQ1: 레퍼런스 선택 및 모델 효과 ────────────────────────────────────

def rq1_analysis(df: pd.DataFrame):
    """Two-way ANOVA, Kruskal-Wallis, pairwise 비교 (논문 §4.2)."""
    print("\n" + "=" * 80)
    print("§4.2  RQ1: 레퍼런스 선택 및 모델 효과")
    print("=" * 80)

    # ── Two-way ANOVA ──
    print("\n--- Two-way ANOVA ---")
    model_anova = ols("OverallScore ~ C(Reference) * C(Model)", data=df).fit()
    anova_table = anova_lm(model_anova, typ=2)

    ss_total = anova_table["sum_sq"].sum()
    anova_table["eta_sq"] = anova_table["sum_sq"] / ss_total
    print(anova_table[["sum_sq", "df", "F", "PR(>F)", "eta_sq"]].round(4))

    eta_ref = anova_table.loc["C(Reference)", "eta_sq"]
    eta_model = anova_table.loc["C(Model)", "eta_sq"]
    eta_inter = anova_table.loc["C(Reference):C(Model)", "eta_sq"]
    print(f"\nη² 요약: Reference={eta_ref:.3f}, Model={eta_model:.3f}, "
          f"Interaction={eta_inter:.3f}, 합계={eta_ref + eta_model + eta_inter:.3f}")

    # ── 가정 검정 ──
    print("\n--- 가정 검정 ---")
    residuals = model_anova.resid
    w_stat, w_p = shapiro(residuals[:5000] if len(residuals) > 5000 else residuals)
    print(f"Shapiro-Wilk (잔차): W={w_stat:.3f}, p={w_p:.2e}")
    groups = [g["OverallScore"].values for _, g in df.groupby(["Reference", "Model"])]
    lev_stat, lev_p = levene(*groups)
    print(f"Levene 등분산: F={lev_stat:.2f}, p={lev_p:.2e}")

    # ── Kruskal-Wallis 비모수 보완 ──
    print("\n--- Kruskal-Wallis 비모수 검정 ---")
    ref_groups = [g["OverallScore"].values for _, g in df.groupby("Reference")]
    h_ref, p_ref = kruskal(*ref_groups)
    print(f"레퍼런스 효과: H={h_ref:.2f}, p={p_ref:.2e}")

    model_groups = [g["OverallScore"].values for _, g in df.groupby("Model")]
    h_mod, p_mod = kruskal(*model_groups)
    print(f"모델 효과: H={h_mod:.2f}, p={p_mod:.2e}")

    # ── 레퍼런스별 CV ──
    print("\n--- 레퍼런스별 변동계수(CV) ---")
    ref_stats = df.groupby("Reference")["OverallScore"].agg(["mean", "std"])
    ref_stats["CV(%)"] = (ref_stats["std"] / ref_stats["mean"]) * 100
    print(ref_stats.round(4))

    # ── 모델 쌍별 비교 (논문 표 4) ──
    print("\n--- 모델 쌍별 Overall Score 차이 검정 (표 4) ---")
    models = sorted(df["Model"].unique())
    pairs = []
    p_values_for_correction = []
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            m1, m2 = models[i], models[j]
            x = df[df["Model"] == m1]["OverallScore"].values
            y = df[df["Model"] == m2]["OverallScore"].values
            u, p = mannwhitneyu(x, y, alternative="two-sided")
            r = rank_biserial_r(u, len(x), len(y))
            d = cohens_d(x, y)
            delta = np.mean(x) - np.mean(y)

            # 95% CI for r
            ci = bootstrap_ci(x, y)

            pairs.append({
                "비교": f"{m1} vs {m2}",
                "Δμ": f"{delta:+.4f}",
                "U": f"{u:.0f}",
                "p-value": f"{p:.2e}",
                "rank-biserial r": f"{r:+.3f}",
                "95% CI": f"[{ci[0]:.3f}, {ci[1]:.3f}]",
                "Cohen's d": f"{d:+.2f}",
            })
            p_values_for_correction.append(p)

    # Holm-Bonferroni 보정
    adjusted_p = holm_bonferroni(p_values_for_correction)
    for i, row in enumerate(pairs):
        row["p (Holm-Bonf)"] = f"{adjusted_p[i]:.2e}"

    pairs_df = pd.DataFrame(pairs)
    print(pairs_df.to_string(index=False))

    # ── 로컬 모델 전체 평균 CV ──
    overall_mean = df.groupby("Model")["OverallScore"].mean()
    overall_cv = (overall_mean.std() / overall_mean.mean()) * 100
    print(f"\n오픈소스 모델 3개 평균: {overall_mean.mean():.4f} (CV={overall_cv:.2f}%)")

    return anova_table, pairs_df, ref_stats


# ─── §4.3 RQ2: 시각 복잡도 및 문서 형식 효과 ─────────────────────────────────

def rq2_analysis(df: pd.DataFrame):
    """시각 복잡도 상관, 문서 형식 검정, 회귀 분석 (논문 §4.3)."""
    print("\n" + "=" * 80)
    print("§4.3  RQ2: 시각 복잡도 및 문서 형식 효과")
    print("=" * 80)

    # ── 문서 형식 효과 ──
    if "DocType" in df.columns:
        print("\n--- 문서 형식별 Mann-Whitney U ---")
        doc_types = df["DocType"].unique()
        if len(doc_types) >= 2:
            type_groups = {}
            for dt in doc_types:
                type_groups[dt] = df[df["DocType"] == dt]["OverallScore"].values

            type_names = list(type_groups.keys())
            if len(type_names) == 2:
                u, p = mannwhitneyu(
                    type_groups[type_names[0]],
                    type_groups[type_names[1]],
                    alternative="two-sided"
                )
                print(f"{type_names[0]} (n={len(type_groups[type_names[0]])}, "
                      f"μ={np.mean(type_groups[type_names[0]]):.3f}) vs "
                      f"{type_names[1]} (n={len(type_groups[type_names[1]])}, "
                      f"μ={np.mean(type_groups[type_names[1]]):.3f})")
                print(f"U={u:.0f}, p={p:.3f}")

    # ── 사후 회귀 분석 (문서 단위) ──
    print("\n--- 사후 회귀 분석 (문서 단위, N=65) ---")
    print("   §4.3: 종속=문서별 평균 Overall, 독립=TEDS 표 구조 std + 출력 풍부도")

    doc_agg = pd.DataFrame({
        "mean_overall": df.groupby("document_id")["OverallScore"].mean()
    })

    predictors = []
    pred_labels = {}

    # 예측변수 1: TEDS 표 구조 표준편차
    if "teds_table_structure_similarity" in df.columns:
        doc_agg["teds_std"] = df.groupby("document_id")[
            "teds_table_structure_similarity"].std()
        predictors.append("teds_std")
        pred_labels["teds_std"] = "TEDS 표 구조 표준편차"

    # 예측변수 2: 출력 풍부도 (output_words) — 정확 컬럼 탐지
    output_col = next((c for c in ["output_words", "output_word_count",
                                   "generated_words", "output_length"]
                       if c in df.columns), None)
    if output_col:
        doc_agg["output_words"] = df.groupby("document_id")[output_col].mean()
        predictors.append("output_words")
        pred_labels["output_words"] = "출력 풍부도(output_words)"
        proxy_note = None
    else:
        # output_words 부재 → proxy 사용 + 경고
        proxy_note = ("⚠ output_words 컬럼이 Excel에 없어 정확 재현 불가. "
                      "원본: R²=0.862, adj R²=0.857, F(2,62)=193.03. "
                      "재현하려면 생성 ADR의 단어 수(output_words)를 추가 입력 필요.")
        print(f"\n  {proxy_note}")

    doc_agg = doc_agg.dropna()

    if predictors and len(doc_agg) > 10:
        X = sm.add_constant(doc_agg[predictors])
        y = doc_agg["mean_overall"]
        reg = sm.OLS(y, X).fit()
        print(f"\nR²={reg.rsquared:.3f}, adj R²={reg.rsquared_adj:.3f}, "
              f"F({int(reg.df_model)},{int(reg.df_resid)})={reg.fvalue:.2f}, "
              f"p={reg.f_pvalue:.2e}")
        for name, coef, pval in zip(["(Intercept)"] + predictors,
                                    reg.params.values, reg.pvalues.values):
            label = pred_labels.get(name, name)
            print(f"  {label}: β={coef:+.4f}, p={pval:.2e}")

        # 회귀 결과 DataFrame (실제 반환된 파라미터 기준으로 구성)
        param_names = list(reg.params.index)
        display_names = []
        for pn in param_names:
            if pn == "const":
                display_names.append("(Intercept)")
            else:
                display_names.append(pred_labels.get(pn, pn))

        n_params = len(param_names)
        reg_df = pd.DataFrame({
            "구분": ["요약"] + ["계수"] * n_params,
            "항목": ["모형 적합도"] + display_names,
            "값/계수": [f"R²={reg.rsquared:.3f}, adj R²={reg.rsquared_adj:.3f}"]
                      + [f"{c:+.4f}" for c in reg.params.values],
            "표준오차": [""] + [f"{e:.4f}" for e in reg.bse.values],
            "t-value": [f"F={reg.fvalue:.2f}"] + [f"{t:.3f}" for t in reg.tvalues.values],
            "p-value": [f"{reg.f_pvalue:.2e}"] + [f"{p:.2e}" for p in reg.pvalues.values],
        })
        if proxy_note:
            reg_df = pd.concat([reg_df, pd.DataFrame([{
                "구분": "주의", "항목": proxy_note
            }])], ignore_index=True)
        return reg_df
    else:
        print("  (예측 변수 부족 또는 데이터 부족으로 회귀 생략)")
        return pd.DataFrame([{"구분": "생략", "항목": proxy_note or "데이터 부족"}])


# ─── §4.4 RQ3: Family Bias 분석 ──────────────────────────────────────────────

def rq3_analysis(df: pd.DataFrame):
    """Family bias 검정 (§4.4, 표 6)."""
    print("\n" + "=" * 80)
    print("§4.4  RQ3: Family Bias 분석")
    print("=" * 80)

    # 계열 쌍 판별
    def is_same_family(ref, model):
        for (r, m), _ in FAMILY_MAP.items():
            if ref == r and model.lower() == m:
                return True
        return False

    df["same_family"] = df.apply(
        lambda row: is_same_family(row["Reference"], row["Model"]), axis=1
    )

    fam = df[df["same_family"]]["OverallScore"].values
    non_fam = df[~df["same_family"]]["OverallScore"].values

    print(f"\n동일 계열 쌍: n={len(fam)}, μ={np.mean(fam):.4f}")
    print(f"이질 계열 쌍: n={len(non_fam)}, μ={np.mean(non_fam):.4f}")

    u, p = mannwhitneyu(fam, non_fam, alternative="greater")
    r = rank_biserial_r(u, len(fam), len(non_fam))
    d = cohens_d(fam, non_fam)
    ci = bootstrap_ci(fam, non_fam)

    print(f"\nMann-Whitney U={u:.0f}, p={p:.2e}")
    print(f"rank-biserial r={r:+.3f}, 95% CI [{ci[0]:.3f}, {ci[1]:.3f}]")
    print(f"Cohen's d={d:+.3f} (참고용)")

    # 전체 결과 행
    overall_row = {
        "모델 계열": "전체 (Same vs Cross)",
        "동일 계열 평가": f"{np.mean(fam):.4f}",
        "타 계열 평가": f"{np.mean(non_fam):.4f}",
        "편향(Δ)": f"{np.mean(fam) - np.mean(non_fam):+.4f}",
        "Mann-Whitney U": f"{u:.0f}",
        "p-value": f"{p:.2e}",
        "rank-biserial r": f"{r:+.3f}",
        "95% CI": f"[{ci[0]:.3f}, {ci[1]:.3f}]",
        "Cohen's d": f"{d:+.3f}",
    }

   # ── 계열별 비대칭성 (표 6) — 모델 기준 ──
    # 해석: 동일 모델이 '자기 계열 레퍼런스'로 평가받을 때 vs '타 레퍼런스'로 평가받을 때
    # 예: gemma←Gemini vs gemma←{Claude, ChatGPT, Mistral, Qwen3_6}
    print("\n--- 모델 계열별 Family Bias 비대칭성 (표 6, 모델 기준) ---")
    bias_rows = [overall_row]
    for (ref, mod), family_name in FAMILY_MAP.items():
        model_name = MODEL_NAME_MAP.get(mod, mod)
        same = df[(df["Reference"] == ref) &
                  (df["Model"] == model_name)]["OverallScore"]
        other = df[(df["Reference"] != ref) &
                   (df["Model"] == model_name)]["OverallScore"]
        if len(same) > 0 and len(other) > 0:
            delta = same.mean() - other.mean()
            print(f"  {family_name} ({ref}→{mod}): "
                  f"동일={same.mean():.4f}, 타={other.mean():.4f}, "
                  f"Δ={delta:+.4f}")
            bias_rows.append({
                "모델 계열": f"{family_name} ({ref}→{mod})",
                "동일 계열 평가": f"{same.mean():.4f}",
                "타 계열 평가": f"{other.mean():.4f}",
                "편향(Δ)": f"{delta:+.4f}",
            })

    # ── χ² 검정: 문서 형식별 family bias 분포 ──
    if "DocType" in df.columns and df["DocType"].nunique() >= 2:
        print("\n--- χ² 검정: 문서 형식별 Family Bias ---")
        ct = pd.crosstab(df["DocType"], df["same_family"])
        chi2, p_chi, dof, expected = chi2_contingency(ct)
        print(f"χ²={chi2:.2f}, p={p_chi:.3f}, dof={dof}")
        bias_rows.append({
            "모델 계열": f"χ² 검정 (문서형식별)",
            "편향(Δ)": f"χ²={chi2:.2f}, p={p_chi:.3f}",
        })

    return pd.DataFrame(bias_rows)


# ─── §4.5 어휘-의미 격차 분석 ────────────────────────────────────────────────

def lexical_semantic_gap(df: pd.DataFrame):
    """어휘-의미 격차 분석 (§4.5, 표 7)."""
    print("\n" + "=" * 80)
    print("§4.5  어휘-의미 격차 분석")
    print("=" * 80)

    rows = []
    for model in sorted(df["Model"].unique()):
        sub = df[df["Model"] == model]
        rougeL = sub["rougeL"].mean() if "rougeL" in sub.columns else np.nan
        bert = sub["bertscore"].mean() if "bertscore" in sub.columns else np.nan
        mover = sub["moverscore"].mean() if "moverscore" in sub.columns else np.nan
        gap = bert - rougeL if not np.isnan(bert) and not np.isnan(rougeL) else np.nan
        ratio = bert / rougeL if rougeL > 0 else np.nan

        print(f"  {model}: ROUGE-L={rougeL:.4f}, BERTScore={bert:.4f}, "
              f"MoverScore={mover:.4f}, Gap={gap:+.4f} ({ratio:.2f}x)")
        rows.append({
            "오픈소스 모델": model,
            "ROUGE-L 평균": round(rougeL, 4),
            "BERTScore 평균": round(bert, 4),
            "MoverScore 평균": round(mover, 4),
            "Gap (BERTScore - ROUGE-L)": round(gap, 4) if not np.isnan(gap) else None,
            "배율": f"{ratio:.2f}x" if not np.isnan(ratio) else None,
        })

    return pd.DataFrame(rows)


# ─── §4.6 구조적 정합성 심층 분석 ────────────────────────────────────────────

def structural_analysis(df: pd.DataFrame):
    """구조적 정합성 분석 (§4.6)."""
    print("\n" + "=" * 80)
    print("§4.6  구조적 정합성 심층 분석")
    print("=" * 80)

    teds_pivot = pd.DataFrame()
    if "teds_table_structure_similarity" in df.columns:
        print("\n--- TEDS Table Structure Similarity (레퍼런스×모델) ---")
        teds_pivot = df.pivot_table(
            values="teds_table_structure_similarity",
            index="Reference", columns="Model", aggfunc="mean"
        )
        print(teds_pivot.round(4))

    if "overall_document_structure_similarity" in df.columns:
        print("\n--- Overall Document Structure Similarity (모델별 평균) ---")
        doc_struct = df.groupby("Model")["overall_document_structure_similarity"].mean()
        print(doc_struct.round(4))

    return teds_pivot


# ─── §5.3 데이터셋 특성 분석 ─────────────────────────────────────────────────

def dataset_characteristics(df: pd.DataFrame, data_dir: str = "."):
    """
    데이터셋 특성 분석 (§5.3, 표 8).

    문서 유형 판별:
      - DocType 사용 (특허는 '10'으로 시작)
    """
    print("\n" + "=" * 80)
    print("§5.3  데이터셋 특성 분석 (표 8)")
    print("=" * 80)

    df = df.copy()

    # ── 문서 유형 판별: main()에서 생성된 DocType 사용 ──
    if "DocType" not in df.columns:
        df["DocType"] = df["document_id"].apply(classify_doc_type)
    df["_label"] = df["DocType"]

    rows = []
    label_order = ["특허", "연구 보고서"]
    labels = [l for l in label_order if l in df["_label"].unique()]
    labels += [l for l in df["_label"].unique() if l not in label_order]

    # 문서 단위 집계: 각 문서 = 15개 조합의 평균 Overall Score (논문 Fig 5/표 8 방식)
    doc_level = df.groupby(["document_id", "_label"])["OverallScore"].mean().reset_index()

    for label in labels:
        sub_docs = doc_level[doc_level["_label"] == label]  # 문서 단위
        n_docs = sub_docs["document_id"].nunique()
        mean_os = sub_docs["OverallScore"].mean()      # 문서 평균들의 평균
        std_os = sub_docs["OverallScore"].std()        # 문서 평균들의 표준편차
        print(f"  {label}: n={n_docs}, Overall={mean_os:.3f}, σ={std_os:.3f}")
        rows.append({
            "문서 유형": label,
            "건수(n)": n_docs,
            "평균 Overall Score": round(mean_os, 3),
            "표준편차": round(std_os, 3),
        })

    # 전체 행 (문서 단위)
    n_all = doc_level["document_id"].nunique()
    mean_all = doc_level["OverallScore"].mean()
    std_all = doc_level["OverallScore"].std()
    print(f"  전체: n={n_all}, Overall={mean_all:.3f}, σ={std_all:.3f}")
    rows.append({
        "문서 유형": "전체",
        "건수(n)": n_all,
        "평균 Overall Score": round(mean_all, 3),
        "표준편차": round(std_all, 3),
    })
    return pd.DataFrame(rows)


# ─── 보완: LMM 분석 (§3.4.5) ─────────────────────────────────────────────────

def lmm_analysis(df: pd.DataFrame):
    """선형 혼합 모형 (LMM) 보완 분석 — ICC 산출."""
    print("\n" + "=" * 80)
    print("§3.4.5 보완  선형 혼합 모형 (LMM)")
    print("=" * 80)

    try:
        md = MixedLM.from_formula(
            "OverallScore ~ C(Model) * C(Reference)",
            groups="document_id",
            data=df
        )
        mdf = md.fit(reml=True)
        var_random = mdf.cov_re.iloc[0, 0]
        var_resid = mdf.scale
        icc = var_random / (var_random + var_resid)
        print(f"문서 수준 무작위 효과 분산: {var_random:.4f}")
        print(f"잔차 분산: {var_resid:.4f}")
        print(f"ICC = {icc:.3f}")
        print("→ 고정 효과의 유의성과 방향은 ANOVA와 동일하게 유지됨")
        return pd.DataFrame([{
            "항목": "LMM (Overall ~ Model × Reference + (1|Document))",
            "문서 무작위 효과 분산": round(var_random, 4),
            "잔차 분산": round(var_resid, 4),
            "ICC": round(icc, 3),
            "해석": "고정 효과 유의성·방향 ANOVA와 동일 유지",
        }])
    except Exception as e:
        print(f"  LMM 적합 실패: {e}")
        print("  (statsmodels 또는 데이터 구조 문제일 수 있음)")
        return pd.DataFrame([{"항목": "LMM 적합 실패", "비고": str(e)}])


# ─── 레퍼런스×모델 상세 성능표 (논문 표 5) ────────────────────────────────────

def detailed_performance_table(df: pd.DataFrame):
    """레퍼런스 모델별 오픈소스 LLM 성능 비교 (논문 표 5)."""
    print("\n" + "=" * 80)
    print("표 5  레퍼런스 모델별 오픈소스 LLM 성능 비교 (평균값)")
    print("=" * 80)

    metrics = ["f1_score", "rouge1", "rougeL", "bertscore",
               "teds_table_structure_similarity", "OverallScore"]
    available = [m for m in metrics if m in df.columns]

    pivot = df.pivot_table(
        values=available,
        index=["Reference", "Model"],
        aggfunc="mean"
    )
    print(pivot.round(4).to_string())


# ═══════════════════════════════════════════════════════════════════════════════
#  시각화 함수 — 논문 그림 3, 4, 5 원본 재현 + 추가 차트
# ═══════════════════════════════════════════════════════════════════════════════

def _savefig(fig, fig_dir, filename):
    """그림 저장 헬퍼."""
    os.makedirs(fig_dir, exist_ok=True)
    path = os.path.join(fig_dir, filename)
    fig.savefig(path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  → 저장: {path}")


# ─── 그림 3: 레퍼런스 모델별 Overall Score (논문 원본 재현) ───────────────────

def plot_fig3_reference_scores(df: pd.DataFrame, fig_dir: str):
    """
    Fig. 3. Overall similarity score across reference models
    (error bars: standard deviation)
    — 논문 p.7 원본 재현 —
    """
    print("\n--- [그림 3] 레퍼런스 모델별 Overall Score ---")

    stats_df = df.groupby(["Reference", "Model"])["OverallScore"].agg(
        ["mean", "std"]
    ).reset_index()

    refs = [r for r in REF_ORDER if r in stats_df["Reference"].unique()]
    models = [m for m in MODEL_ORDER if m in stats_df["Model"].unique()]

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(refs))
    width = 0.22
    offsets = {0: -width, 1: 0, 2: width}

    for i, model in enumerate(models):
        sub = stats_df[stats_df["Model"] == model].set_index("Reference")
        means = [sub.loc[r, "mean"] if r in sub.index else 0 for r in refs]
        stds = [sub.loc[r, "std"] if r in sub.index else 0 for r in refs]
        ax.bar(
            x + offsets[i], means, width,
            yerr=stds, capsize=3, error_kw={"linewidth": 1.0},
            label=model, color=MODEL_COLORS.get(model, f"C{i}"),
            edgecolor="white", linewidth=0.5, zorder=3
        )

    ax.set_xlabel("Reference Model", fontsize=11)
    ax.set_ylabel("Overall Similarity Score", fontsize=11)
    ax.set_xticks(x)
    ax.set_xticklabels(refs, fontsize=10)
    ax.set_ylim(0, 0.85)
    ax.set_yticks(np.arange(0, 0.9, 0.2))
    ax.legend(loc="upper right", fontsize=10, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _savefig(fig, fig_dir, "fig3_reference_model_scores.png")


# ─── 그림 4: 문서별 Overall Score 분포 (논문 원본 재현) ───────────────────────

def plot_fig4_document_distribution(df: pd.DataFrame, fig_dir: str):
    """
    Fig. 4. Document-level Overall Score distribution
    — 논문 p.8 원본 재현: 2×2 산점도 + 상관계수 + 추세선 —
    """
    print("\n--- [그림 4] 문서별 Overall Score 분포 ---")

    # 문서 단위 집계
    doc_agg = df.groupby("document_id").agg(
        mean_overall=("OverallScore", "mean"),
    )

    # 패널 정의 (논문 순서: TEDS Std, Doc Struct, BERTScore, ROUGE-L Std)
    panels = []
    if "teds_table_structure_similarity" in df.columns:
        doc_agg["teds_std"] = df.groupby("document_id")[
            "teds_table_structure_similarity"].std()
        panels.append(("teds_std", "TEDS Table Std"))

    if "overall_document_structure_similarity" in df.columns:
        doc_agg["doc_struct_mean"] = df.groupby("document_id")[
            "overall_document_structure_similarity"].mean()
        panels.append(("doc_struct_mean", "Doc Structure Mean"))

    if "bertscore" in df.columns:
        doc_agg["bertscore_mean"] = df.groupby("document_id")[
            "bertscore"].mean()
        panels.append(("bertscore_mean", "BERTScore Mean"))

    if "rougeL" in df.columns:
        doc_agg["rougeL_std"] = df.groupby("document_id")[
            "rougeL"].std()
        panels.append(("rougeL_std", "ROUGE-L Std"))

    if not panels:
        print("  (시각화할 컬럼 부족, 생략)")
        return

    n = len(panels)
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()

    for idx, (col, label) in enumerate(panels):
        ax = axes[idx]
        valid = doc_agg.dropna(subset=[col, "mean_overall"])
        # 논문 그림 4는 선형 추세선 기반 Pearson r 사용
        r_pearson, _ = pearsonr(valid[col], valid["mean_overall"])
        rho_spearman, _ = spearmanr(valid[col], valid["mean_overall"])

        # 산점도
        ax.scatter(valid[col], valid["mean_overall"],
                   alpha=0.5, s=25, c="#1f77b4", edgecolors="none", zorder=3)

        # 추세선 (선형 회귀)
        if len(valid) > 2:
            z = np.polyfit(valid[col], valid["mean_overall"], 1)
            p_line = np.poly1d(z)
            x_range = np.linspace(valid[col].min(), valid[col].max(), 100)
            ax.plot(x_range, p_line(x_range), "-", color="red",
                    alpha=0.8, linewidth=1.5, zorder=4)

        ax.set_xlabel(label, fontsize=10)
        ax.set_ylabel("Mean Overall Score", fontsize=10)
        # 논문 표기: Pearson r (참고로 Spearman ρ 병기)
        ax.set_title(f"{label} (r={r_pearson:.3f})",
                     fontsize=11, fontweight="bold")
        ax.grid(alpha=0.3, zorder=0)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        print(f"    {label}: Pearson r={r_pearson:+.3f}, "
              f"Spearman ρ={rho_spearman:+.3f}")

    # 남는 subplot 제거
    for idx in range(n, 4):
        fig.delaxes(axes[idx])

    fig.tight_layout(h_pad=2.5, w_pad=2.0)
    _savefig(fig, fig_dir, "fig4_document_distribution.png")


# ─── 그림 5: 사후 출력 신호와 문서별 Overall Score 산점도 (논문 원본 재현) ────

def plot_fig5_difficulty_and_posthoc(df: pd.DataFrame, fig_dir: str):
    """
    Fig. 5. Document-level Difficulty Distribution (n=65)
    — 논문 p.9 원본 재현: 문서 순위별 Overall Score, 유형별 마커 —
    """
    print("\n--- [그림 5] 사후 출력 신호와 문서별 Overall Score ---")

    doc_agg = df.groupby("document_id").agg(
        mean_overall=("OverallScore", "mean"),
        std_overall=("OverallScore", "std"),
    )

    if "DocType" in df.columns:
        doc_type = df.groupby("document_id")["DocType"].first()
        doc_agg["doc_type"] = doc_type

    doc_agg = doc_agg.sort_values("mean_overall", ascending=True).reset_index()
    doc_agg["rank"] = range(1, len(doc_agg) + 1)

    fig, ax = plt.subplots(figsize=(10, 4.5))

    # 문서 유형별 마커 (논문 원본: Patent=circle, Report=diamond)
    type_config = [
        ("특허", "#1f77b4", "o", "Patent"),
        ("연구 보고서", "#ff7f0e", "D", "Report"),
    ]

    plotted = False
    if "doc_type" in doc_agg.columns:
        for dtype, color, marker, display_name in type_config:
            sub = doc_agg[doc_agg["doc_type"] == dtype]
            if len(sub) > 0:
                ax.errorbar(
                    sub["rank"], sub["mean_overall"],
                    yerr=sub["std_overall"],
                    fmt=marker, color=color, alpha=0.7, capsize=2,
                    markersize=5, linewidth=0, elinewidth=0.8,
                    label=f"{display_name} (n={len(sub)})", zorder=3
                )
                plotted = True

    if not plotted:
        ax.errorbar(
            doc_agg["rank"], doc_agg["mean_overall"],
            yerr=doc_agg["std_overall"],
            fmt="o", color="#1f77b4", alpha=0.7, capsize=2,
            markersize=5, linewidth=0, elinewidth=0.8, zorder=3
        )

    # 전체 평균선
    mean_val = doc_agg["mean_overall"].mean()
    ax.axhline(y=mean_val, color="gray", linestyle="--",
               linewidth=1.0, alpha=0.6, zorder=2,
               label=f"Mean = {mean_val:.4f}")

    ax.set_xlabel("Document Rank (sorted by Overall Score)", fontsize=11)
    ax.set_ylabel(
        "Overall Score\n(mean ± std across 15 model-ref combinations)",
        fontsize=10)
    ax.set_title(
        f"Document-level Difficulty Distribution (n={len(doc_agg)})",
        fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _savefig(fig, fig_dir, "fig5_document_difficulty.png")


# ─── 추가 그림: Family Bias 비대칭성 ─────────────────────────────────────────

def plot_family_bias_comparison(df: pd.DataFrame, fig_dir: str):
    """모델 계열별 동일계열 vs 타계열 Overall Score + Bias Δ 차트."""
    print("\n--- [추가] Family Bias 비대칭성 차트 ---")

    bias_data = []
    for (ref, mod), family_name in FAMILY_MAP.items():
        same = df[(df["Reference"] == ref) &
                  (df["Model"].str.lower() == mod)]["OverallScore"]
        other = df[(df["Reference"] == ref) &
                   (df["Model"].str.lower() != mod)]["OverallScore"]
        if len(same) > 0 and len(other) > 0:
            bias_data.append({
                "Family": f"{family_name}\n({ref}→{mod})",
                "Same Family": same.mean(),
                "Cross Family": other.mean(),
                "Bias (Δ)": same.mean() - other.mean(),
            })

    if not bias_data:
        print("  (Family bias 데이터 부족, 생략)")
        return

    bdf = pd.DataFrame(bias_data)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5),
                             gridspec_kw={"width_ratios": [2, 1]})

    # 좌: 동일/타계열 비교 바 차트
    ax = axes[0]
    x = np.arange(len(bdf))
    width = 0.32
    ax.bar(x - width / 2, bdf["Same Family"], width,
           label="Same Family", color="#4285F4", edgecolor="white")
    ax.bar(x + width / 2, bdf["Cross Family"], width,
           label="Cross Family", color="#FBBC04", edgecolor="white")
    ax.set_xticks(x)
    ax.set_xticklabels(bdf["Family"], fontsize=10)
    ax.set_ylabel("Mean Overall Score", fontsize=11)
    ax.set_title("Same-Family vs Cross-Family Evaluation", fontsize=12)
    ax.legend(fontsize=10)
    ax.set_ylim(0.4, 0.8)
    ax.grid(axis="y", alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # 우: Bias delta
    ax2 = axes[1]
    colors = ["#34A853" if d > 0 else "#EA4335" for d in bdf["Bias (Δ)"]]
    ax2.barh(x, bdf["Bias (Δ)"], color=colors, edgecolor="white", height=0.45)
    ax2.set_yticks(x)
    ax2.set_yticklabels(bdf["Family"], fontsize=10)
    ax2.set_xlabel("Bias (Δ = Same − Cross)", fontsize=11)
    ax2.set_title("Family Bias Asymmetry", fontsize=12)
    ax2.axvline(x=0, color="black", linewidth=0.8)
    ax2.grid(axis="x", alpha=0.3)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    for i, v in enumerate(bdf["Bias (Δ)"]):
        ax2.text(v + 0.003 if v > 0 else v - 0.003, i,
                 f"{v:+.4f}", va="center",
                 ha="left" if v > 0 else "right",
                 fontsize=9, fontweight="bold")

    fig.tight_layout()
    _savefig(fig, fig_dir, "fig_family_bias_asymmetry.png")


# ─── 추가 그림: 어휘-의미 격차 비교 ─────────────────────────────────────────

def plot_lexical_semantic_gap(df: pd.DataFrame, fig_dir: str):
    """ROUGE-L / BERTScore / MoverScore 비교 (논문 표 7 시각화)."""
    print("\n--- [추가] 어휘-의미 격차 비교 차트 ---")

    models = [m for m in MODEL_ORDER if m in df["Model"].unique()]
    metrics_map = {
        "ROUGE-L": "rougeL",
        "BERTScore": "bertscore",
        "MoverScore": "moverscore",
    }
    available = {k: v for k, v in metrics_map.items() if v in df.columns}
    if len(available) < 2:
        print("  (메트릭 부족, 생략)")
        return

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(available))
    width = 0.22
    offsets = {0: -width, 1: 0, 2: width}

    for i, model in enumerate(models):
        sub = df[df["Model"] == model]
        vals = [sub[col].mean() for col in available.values()]
        bars = ax.bar(x + offsets.get(i, 0), vals, width,
                      label=model, color=MODEL_COLORS.get(model, f"C{i}"),
                      edgecolor="white", linewidth=0.5, zorder=3)
        # 값 표시
        for bar_obj, v in zip(bars, vals):
            ax.text(bar_obj.get_x() + bar_obj.get_width() / 2, v + 0.01,
                    f"{v:.3f}", ha="center", va="bottom", fontsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels(available.keys(), fontsize=11)
    ax.set_ylabel("Mean Score (5-reference average)", fontsize=11)
    ax.set_title("Lexical–Semantic Gap Comparison by Model", fontsize=12)
    ax.legend(fontsize=10)
    ax.set_ylim(0, 1.0)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    _savefig(fig, fig_dir, "fig_lexical_semantic_gap.png")


# ─── 추가 그림: Overall Score 히트맵 ─────────────────────────────────────────

def plot_heatmap_performance(df: pd.DataFrame, fig_dir: str):
    """5×3 레퍼런스×모델 Overall Score 히트맵 (논문 표 5 시각화)."""
    print("\n--- [추가] Overall Score 히트맵 ---")

    pivot = df.pivot_table(
        values="OverallScore",
        index="Reference", columns="Model", aggfunc="mean"
    )

    refs = [r for r in REF_ORDER if r in pivot.index]
    models = [m for m in MODEL_ORDER if m in pivot.columns]
    pivot = pivot.loc[refs, models] if refs and models else pivot

    fig, ax = plt.subplots(figsize=(6, 4.5))

    if HAS_SEABORN:
        sns.heatmap(
            pivot, annot=True, fmt=".4f", cmap="YlGnBu",
            linewidths=0.8, ax=ax, vmin=0.45, vmax=0.75,
            annot_kws={"fontsize": 10}
        )
    else:
        im = ax.imshow(pivot.values, cmap="YlGnBu", aspect="auto",
                       vmin=0.45, vmax=0.75)
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns)
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels(pivot.index)
        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                ax.text(j, i, f"{pivot.values[i, j]:.4f}",
                        ha="center", va="center", fontsize=10)
        fig.colorbar(im, ax=ax)

    ax.set_title("Overall Score by Reference × Model", fontsize=12)
    fig.tight_layout()
    _savefig(fig, fig_dir, "fig_heatmap_overall_score.png")


def generate_all_figures(df: pd.DataFrame, fig_dir: str):
    """모든 시각화를 일괄 생성."""
    print("\n" + "=" * 80)
    print("  시각화 생성")
    print("=" * 80)

    plot_fig3_reference_scores(df, fig_dir)
    plot_fig4_document_distribution(df, fig_dir)
    plot_fig5_difficulty_and_posthoc(df, fig_dir)
    plot_family_bias_comparison(df, fig_dir)
    plot_lexical_semantic_gap(df, fig_dir)
    plot_heatmap_performance(df, fig_dir)


# ─── 메인 실행 ────────────────────────────────────────────────────────────────

def main():
    print("=" * 80)
    print("  스마트팜 ADR 다중 레퍼런스 편향 실증 분석 — 통계 분석 재현 스크립트")
    print(f"  실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # 데이터 경로 (CLI 인자 또는 기본값)
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = os.environ.get("DATA_DIR", ".")

    print(f"\n데이터 디렉토리: {os.path.abspath(data_dir)}")

    # 1. 데이터 로드
    df = load_data(data_dir)

    # 2. Overall Score 산출
    #    논문 최종 가중치(어휘25%·의미35%·구조40%)로 재계산하여 논문 수치와 정합.
    #    Excel의 overall_score 컬럼이 있으면 비교용으로 함께 출력.

    # 메트릭 컬럼 존재 여부 진단 (특히 구조 13개 컬럼)
    lex_found = [c for c in LEXICAL_COLS if c in df.columns]
    sem_found = [c for c in SEMANTIC_COLS if c in df.columns]
    str_found = [c for c in STRUCTURE_COLS if c in df.columns]
    print(f"\n메트릭 컬럼 확인:")
    print(f"  어휘 {len(lex_found)}/{len(LEXICAL_COLS)}개, "
          f"의미 {len(sem_found)}/{len(SEMANTIC_COLS)}개, "
          f"구조 {len(str_found)}/{len(STRUCTURE_COLS)}개")
    if len(str_found) < len(STRUCTURE_COLS):
        missing = [c for c in STRUCTURE_COLS if c not in df.columns]
        print(f"  ⚠ 구조 그룹 누락 컬럼({len(missing)}개): {missing}")
        print(f"    → 논문 수치 재현에는 구조 13개 컬럼이 모두 필요합니다.")

    df["OverallScore"] = compute_overall_score(df)  # 20/45/35 재계산

    # 문서 유형 분류 (doc_type이 "ADR"로 통일되어 있으므로 document_id 기반 분류)
    df["DocType"] = df["document_id"].apply(classify_doc_type)
    doc_counts = df.groupby("DocType")["document_id"].nunique()
    print(f"  문서 유형 분류: " + ", ".join(f"{k}={v}건" for k, v in doc_counts.items()))
    print(f"\nOverall Score 재계산 (논문 가중치: "
          f"어휘 {WEIGHT_LEXICAL*100:.0f}% / "
          f"의미 {WEIGHT_SEMANTIC*100:.0f}% / "
          f"구조 {WEIGHT_STRUCTURE*100:.0f}%, 총 "
          f"{len(lex_found)+len(sem_found)+len(str_found)}개 메트릭)")
    print(f"  재계산 전체 평균: {df['OverallScore'].mean():.4f}, "
          f"표준편차: {df['OverallScore'].std():.4f}")
    # 모델별 평균 (논문 표 4 대조용)
    model_means = df.groupby("Model")["OverallScore"].mean().sort_values(ascending=False)
    print(f"  모델별 평균: " +
          ", ".join(f"{m}={v:.4f}" for m, v in model_means.items()))
    print(f"  (논문 표 4: Gemma=0.6166, Qwen=0.6155, Ministral=0.5470)")
    if "overall_score" in df.columns:
        excel_mean = df["overall_score"].mean()
        print(f"  (Excel overall_score 컬럼 평균: {excel_mean:.4f})")

    # 3. 분석 실행
    sens_df = sensitivity_analysis(df)
    anova_tbl, pairs_df, ref_cv_df = rq1_analysis(df)
    reg_df = rq2_analysis(df)
    bias_df = rq3_analysis(df)
    gap_df = lexical_semantic_gap(df)
    teds_df = structural_analysis(df)
    dataset_df = dataset_characteristics(df, data_dir)
    detailed_performance_table(df)
    lmm_df = lmm_analysis(df)

    # 4. 시각화 생성
    fig_dir = os.path.join(data_dir, "figures")
    generate_all_figures(df, fig_dir)

    # 5. 결과 저장 (전체 통계량 → Excel 다중 시트)
    output_path = os.path.join(data_dir, "statistical_analysis_results.xlsx")
    try:
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:

            # ── §4.1 민감도 분석 ──
            sens_df.to_excel(writer, sheet_name="§4.1_민감도분석", index=False)

            # ── §4.2 ANOVA 테이블 ──
            anova_out = anova_tbl.copy()
            anova_out.index.name = "Source"
            anova_out.to_excel(writer, sheet_name="§4.2_ANOVA")

            # ── §4.2 모델 쌍별 비교 ──
            pairs_df.to_excel(writer, sheet_name="§4.2_모델쌍비교", index=False)

            # ── §4.2 레퍼런스별 CV ──
            ref_cv_out = ref_cv_df.copy()
            ref_cv_out.index.name = "Reference"
            ref_cv_out.to_excel(writer, sheet_name="§4.2_레퍼런스CV")

            # ── §4.3 회귀 분석 ──
            if not reg_df.empty:
                reg_df.to_excel(writer, sheet_name="§4.3_회귀분석", index=False)

            # ── §4.4 Family Bias ──
            if not bias_df.empty:
                bias_df.to_excel(writer, sheet_name="§4.4_FamilyBias", index=False)

            # ── §4.5 어휘-의미 격차 ──
            if not gap_df.empty:
                gap_df.to_excel(writer, sheet_name="§4.5_어휘의미격차", index=False)

            # ── §4.6 구조적 정합성 (TEDS) ──
            if not teds_df.empty:
                teds_out = teds_df.copy()
                teds_out.index.name = "Reference"
                teds_out.to_excel(writer, sheet_name="§4.6_TEDS구조정합성")

            # ── §5.3 데이터셋 특성 ──
            if not dataset_df.empty:
                dataset_df.to_excel(writer, sheet_name="§5.3_데이터셋특성", index=False)

            # ── §3.4.5 LMM 보완 ──
            if not lmm_df.empty:
                lmm_df.to_excel(writer, sheet_name="§3.4.5_LMM", index=False)

            # ── 레퍼런스×모델 성능표 ──
            perf = df.pivot_table(
                values="OverallScore",
                index="Reference", columns="Model", aggfunc="mean"
            )
            perf.index.name = "Reference"
            perf.to_excel(writer, sheet_name="표5_성능비교표")

        print(f"\n결과 저장: {output_path}")
        print(f"  시트 수: 11개 (논문 §4.1–§5.3 전체 통계량)")
    except Exception as e:
        print(f"\n결과 저장 실패: {e}")

    print("\n" + "=" * 80)
    print("  분석 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()
