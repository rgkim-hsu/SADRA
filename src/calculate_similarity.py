"""
calculate_similarity_revised.py

여러 LLM이 생성한 마크다운 문서를 다양한 메트릭으로 비교·평가하는 스크립트.
기준 모델(reference)을 순차적으로 교체하며 나머지 모델들과 쌍별 비교를 수행합니다.

================================================================================
 사전 준비 (Prerequisites)
================================================================================

  필수 패키지:
    pip install numpy pandas torch nltk rouge-score scikit-learn
    pip install bert-score sentence-transformers transformers scipy openpyxl

  선택 패키지 (설치 시 성능/기능 향상):
    pip install kiwipiepy          # 한국어 형태소 기반 BLEU (미설치 시 음절 단위 fallback)
    pip install moverscore          # MoverScore 라이브러리 (미설치 시 STS+EMD fallback)

  구조 유사도:
    MDEval의 Markdown Awareness와 PubTabNet/TEDS의 tree edit distance 개념을
    순수 Python 구현으로 반영하므로 추가 패키지가 필요 없습니다.

  GPU 가속:
    CUDA 환경이 감지되면 BERTScore, STS, MoverScore 등이 자동으로 GPU를 활용합니다.

================================================================================
 지원 모델 (Model Registry)
================================================================================

  주요 모델 (파일명 토큰 → 표시명):
    gemini    → Gemini
    claude    → Claude
    chatgpt   → ChatGPT
    qwen3_6   → Qwen3.6      (파일명 예: ..._qwen3_6_ADR.md)
    mistral   → Mistral

  하위 호환 / 확장 모델:
    gpt       → ChatGPT      (레거시 파일명 호환)
    llama     → LLaMA
    qwen      → Qwen
    gemma     → Gemma
    ministral → Ministral

  새 모델 추가:
    _MODEL_REGISTRY 딕셔너리에 '토큰': '표시명' 형태로 추가하면 됩니다.
    파일명 토큰은 반드시 소문자로 지정합니다.

================================================================================
 지원 문서 타입 (Document Types)
================================================================================

    ADR, PRD, TestPlan

================================================================================
 파일명 규칙 (Naming Convention)
================================================================================

  형식: {document_id}_{model_token}_{doc_type}.md

  예시:
    1020200184565B1_1_2_gemini_ADR.md       → doc_id='1020200184565B1_1_2', model='gemini',  type='ADR'
    1020200184565B1_1_2_claude_PRD.md       → doc_id='1020200184565B1_1_2', model='claude',  type='PRD'
    1020200184565B1_1_2_qwen3_6_TestPlan.md → doc_id='1020200184565B1_1_2', model='qwen3_6', type='TestPlan'
    1020200184565B1_1_2_chatgpt_TestPlan.md → doc_id='1020200184565B1_1_2', model='chatgpt', type='TestPlan'

  참고:
    - doc_type은 대소문자 무관 (TestPlan, testplan, TESTPLAN 모두 인식)
    - model_token은 최대 4개의 '_' 구분 토큰을 결합하여 매칭 (예: qwen3_6)

================================================================================
 CLI 옵션 (Command-Line Interface)
================================================================================

  python calculate_similarity_revised.py [OPTIONS]

  옵션:
    -i, --input-dir DIR       마크다운 파일이 있는 디렉토리
                              (기본값: GENERATED_DOCS_DIR 환경변수 또는 현재 디렉토리)

    -r, --reference MODEL...  기준 모델 지정 (복수 가능)
                              미지정 시 파일에서 발견된 모든 모델을 순차 실행

    -c, --compare MODEL...    비교 대상 모델 제한 (복수 가능)
                              미지정 시 기준 모델 외 모든 모델과 비교

    --log-file PATH           로그 파일 경로 지정
                              미지정 시 similarity_run_{timestamp}.log 자동 생성

================================================================================
 실행 예시 (Usage Examples)
================================================================================

  # 1. 기본 실행: 모든 모델을 순차적으로 기준 모델로 삼아 전체 비교
  python calculate_similarity_revised.py

  # 2. 특정 기준 모델만 실행
  python calculate_similarity_revised.py --reference gemini
  python calculate_similarity_revised.py --reference claude chatgpt

  # 3. 입력 디렉토리 지정
  python calculate_similarity_revised.py --input-dir D:/generated_docs

  # 4. 비교 대상 모델 제한 (gemini 기준으로 claude, chatgpt만 비교)
  python calculate_similarity_revised.py --reference gemini --compare claude chatgpt

  # 5. 환경변수로 입력 경로 지정
  set GENERATED_DOCS_DIR=D:/generated_docs
  python calculate_similarity_revised.py

  # 6. 로그 파일 명시 지정
  python calculate_similarity_revised.py --log-file my_run.log

  # 7. 전체 조합 예시
  python calculate_similarity_revised.py -i D:/docs -r gemini claude -c chatgpt mistral --log-file run.log

================================================================================
 출력 결과 (Output)
================================================================================

  Excel 파일 (기준 모델별 1개):
    similarity_{model}_as_reference_{timestamp}.xlsx

    컬럼 구성:
      - document_id, doc_type, reference_model, comparison_model
      - Lexical  : f1_score, rouge1, rouge2, rougeL, bleu_score, tfidf_similarity
      - Semantic : bertscore, sts_score, moverscore
      - Structure: markdown_awareness_similarity,
                   teds_document_structure_similarity,
                   teds_table_structure_similarity,
                   overall_document_structure_similarity
      - 종합    : overall_score (lexical 20% + semantic 45% + structure 35%)

  로그 파일:
    similarity_run_{timestamp}.log (콘솔: INFO, 파일: DEBUG)

================================================================================
 내부 아키텍처 (Architecture Overview)
================================================================================

  DocumentCache   : 문서별 텍스트/토큰/임베딩/구조분석 결과를 캐싱
  전역 TF-IDF     : 전체 코퍼스 대상 TF-IDF Vectorizer를 한 번만 학습
  Lazy Loading    : STS/BERTScorer/MoverScore 모델을 첫 호출 시에만 로드
  reset_global_state() : 테스트/반복 실행 시 전역 상태 초기화 유틸리티

================================================================================
"""

import argparse
import glob
import logging
import os
import random
import re
import traceback
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import torch
from nltk.translate.bleu_score import SmoothingFunction, sentence_bleu
from rouge_score import rouge_scorer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import f1_score
from sklearn.metrics.pairwise import cosine_similarity
from bert_score import BERTScorer
from sentence_transformers import SentenceTransformer, util
from transformers import AutoTokenizer, AutoModel
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import cdist

# ── 로깅 설정 ─────────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)


def setup_logging(log_file: str | None = None) -> None:
    """콘솔(INFO) + 파일(DEBUG) 이중 로깅을 설정합니다.

    노트북/테스트 환경에서 main()을 여러 번 실행해도 로그 핸들러가
    중복으로 쌓이지 않도록 기존 핸들러를 먼저 제거합니다.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    if root.handlers:
        root.handlers.clear()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    root.addHandler(console)

    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        root.addHandler(fh)


# ── kiwipiepy (한국어 형태소 분석기) ──────────────────────────────────────────
try:
    from kiwipiepy import Kiwi
    _kiwi = Kiwi()
    KIWI_AVAILABLE = True
except ImportError:
    _kiwi = None
    KIWI_AVAILABLE = False
    warnings.warn(
        "kiwipiepy not available. BLEU will fall back to syllable tokenization. "
        "Install: pip install kiwipiepy",
        stacklevel=2,
    )

# ── moverscore ────────────────────────────────────────────────────────────────
try:
    from moverscore import word_mover_score
    MOVERSCORE_AVAILABLE = True
except ImportError:
    try:
        from moverscore_v2 import get_idf_dict, word_mover_score
        MOVERSCORE_AVAILABLE = True
    except ImportError:
        MOVERSCORE_AVAILABLE = False
        warnings.warn(
            "moverscore library not available. MoverScore will use STS+EMD fallback. "
            "Install: pip install moverscore",
            stacklevel=2,
        )

# ── 재현성 시드 ───────────────────────────────────────────────────────────────
RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)
torch.manual_seed(RANDOM_SEED)
if torch.cuda.is_available():
    torch.cuda.manual_seed(RANDOM_SEED)
    torch.cuda.manual_seed_all(RANDOM_SEED)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

# ── BLEU 스무더 ───────────────────────────────────────────────────────────────
# n-gram이 일부 매칭되지 않을 때 BLEU-3/4가 과도하게 0으로 떨어지는 문제를
# 줄이기 위해 method1 스무딩을 사용합니다. 매 호출 인스턴스 생성을 피하기 위해
# 모듈 레벨에서 한 번만 만들어둡니다.
_BLEU_SMOOTHER = SmoothingFunction().method1

# =============================================================================
# 모델/문서 타입 레지스트리
# =============================================================================

# ▼ 새 모델 추가 시 이 두 곳만 수정하면 됩니다 ▼

_DOC_TYPES: list[str] = ['ADR', 'PRD', 'TestPlan']

# canonical 모델 토큰 → 표시명 매핑
# key   : 내부 처리/출력에 사용할 표준 토큰
# value : 출력·컬럼에 사용할 표시명
_MODEL_REGISTRY: dict[str, str] = {
    # 현재 파일명 규칙용 모델명: 모두 소문자 토큰으로 통일합니다.
    'gemini':    'Gemini',
    'claude':    'Claude',
    'chatgpt':   'ChatGPT',
    'qwen3_6':   'Qwen3.6',    # 파일명: ..._qwen3_6_ADR.md
    'mistral':   'Mistral',

    'llama':      'LLaMA',
    'qwen':       'Qwen',
    'gemma':      'Gemma',
    'ministral':  'Ministral',
}

# 파일명/CLI에서 허용하는 legacy alias → canonical 토큰
_MODEL_ALIASES: dict[str, str] = {
    'gpt': 'chatgpt',
}

# 파일명 토큰 집합 (파싱과 CLI에 사용)
_ALL_MODEL_TOKENS: set[str] = set(_MODEL_REGISTRY.keys()) | set(_MODEL_ALIASES.keys())
_CANONICAL_MODEL_TOKENS: set[str] = set(_MODEL_REGISTRY.keys())

# ▲ 여기까지 ▲


def display_name(token: str) -> str:
    """파일명 토큰을 사람이 읽기 좋은 표시명으로 변환합니다."""
    canonical = normalize_model_token(token)
    return _MODEL_REGISTRY.get(canonical, canonical.upper())


def normalize_model_token(token: str) -> str:
    """파일명/CLI 모델 토큰을 내부 canonical 토큰으로 정규화합니다."""
    lower = token.lower()
    return _MODEL_ALIASES.get(lower, lower)


# =============================================================================
# GPU 디바이스 유틸리티
# =============================================================================

def _get_device() -> str:
    """사용 가능한 최적의 디바이스를 반환합니다."""
    return 'cuda' if torch.cuda.is_available() else 'cpu'


# =============================================================================
# 지연 초기화 (Lazy Loading) 모델 관리
# =============================================================================

_sts_model = None
_moverscore_model = None
_moverscore_tokenizer = None
_moverscore_idf_dict = None
_bert_scorer_instance = None

# Semantic metric은 참조/비교 방향을 보존한 상태로 재계산을 줄이기 위해 캐싱합니다.
# key: (metric_name, reference_file, candidate_file), value: metric value
_pairwise_metric_cache: dict[tuple[str, str, str], float] = {}


def _metric_failure(metric_name: str, message: str, exc: Exception | None = None) -> float:
    """Metric 계산 실패를 0점이 아닌 NaN으로 기록하기 위한 공통 처리."""
    if exc is None:
        logger.warning("%s 계산 실패: %s", metric_name, message)
    else:
        logger.error("%s 계산 오류: %s", metric_name, exc)
        logger.debug(traceback.format_exc())
    return float('nan')


def reset_global_state() -> None:
    """테스트용: 모든 전역 캐시와 모델을 초기화합니다."""
    global _sts_model, _moverscore_model, _moverscore_tokenizer
    global _moverscore_idf_dict, _bert_scorer_instance
    global _global_tfidf_vectorizer, _global_tfidf_matrix, _global_tfidf_file_index
    global _doc_cache

    _sts_model = None
    _moverscore_model = None
    _moverscore_tokenizer = None
    _moverscore_idf_dict = None
    _bert_scorer_instance = None
    _global_tfidf_vectorizer = None
    _global_tfidf_matrix = None
    _global_tfidf_file_index = {}
    _doc_cache = DocumentCache()
    _pairwise_metric_cache.clear()
    logger.info("전역 상태가 초기화되었습니다.")


def get_sts_model() -> SentenceTransformer:
    """STS 모델을 처음 호출 시에만 로드합니다."""
    global _sts_model
    if _sts_model is None:
        logger.info("STS 모델 로딩 중: snunlp/KR-SBERT-V40K-klueNLI-augSTS")
        _sts_model = SentenceTransformer('snunlp/KR-SBERT-V40K-klueNLI-augSTS')
        logger.info("STS 모델 로딩 완료")
    return _sts_model


def get_bert_scorer() -> BERTScorer:
    """BERTScorer 객체를 처음 호출 시에만 생성합니다."""
    global _bert_scorer_instance
    if _bert_scorer_instance is None:
        logger.info("BERTScorer 초기화 중 (lang=ko, rescale_with_baseline=False)")
        _bert_scorer_instance = BERTScorer(lang='ko', rescale_with_baseline=False)
        logger.info("BERTScorer 초기화 완료")
    return _bert_scorer_instance


def get_moverscore_model() -> tuple:
    """MoverScore용 BERT 모델을 처음 호출 시에만 로드합니다."""
    global _moverscore_model, _moverscore_tokenizer, _moverscore_idf_dict
    if _moverscore_model is None:
        try:
            model_name = 'klue/bert-base'
            device = _get_device()
            logger.info(f"MoverScore 모델 로딩 중: {model_name} (device={device})")
            _moverscore_tokenizer = AutoTokenizer.from_pretrained(model_name)
            _moverscore_model = AutoModel.from_pretrained(model_name).to(device)
            _moverscore_model.eval()
            _moverscore_idf_dict = {}
            logger.info("MoverScore 모델 초기화 완료")
        except Exception as e:
            logger.error(f"MoverScore 모델 초기화 실패: {e}")
            logger.warning("MoverScore는 STS fallback으로 계산됩니다.")
            _moverscore_model = None
            _moverscore_tokenizer = None
    return _moverscore_model, _moverscore_tokenizer, _moverscore_idf_dict


# =============================================================================
# 문서 캐시 (DocumentCache) - 중복 연산 제거
# =============================================================================

class DocumentCache:
    """문서별 전처리 결과를 캐싱하여 중복 연산을 제거합니다.

    캐싱 대상:
      - 텍스트 / 토큰               (lexical 메트릭용)
      - Awareness 토큰 시퀀스        (MDEval Markdown Awareness용)
      - 문서 구조 트리                (TEDS 문서 구조 유사도용)
      - 테이블 데이터                 (TEDS 표 구조 유사도용)
    """

    def __init__(self):
        self._texts: dict[str, str] = {}
        self._tokens: dict[str, list[str]] = {}
        self._awareness_tokens: dict[str, list[str]] = {}
        self._doc_trees: dict[str, '_TreeNode'] = {}
        self._table_data: dict[str, list[list[list[str]]]] = {}

    def get_text(self, file_path: str) -> str:
        if file_path not in self._texts:
            self._texts[file_path] = load_text(file_path)
        return self._texts[file_path]

    def get_tokens(self, file_path: str) -> list[str]:
        if file_path not in self._tokens:
            text = self.get_text(file_path)
            self._tokens[file_path] = tokenize_korean(text) if text else []
        return self._tokens[file_path]

    def get_awareness_tokens(self, file_path: str) -> list[str]:
        """MDEval Markdown Awareness 토큰 시퀀스를 캐싱하여 반환합니다."""
        if file_path not in self._awareness_tokens:
            text = self.get_text(file_path)
            self._awareness_tokens[file_path] = _markdown_to_awareness_tokens(text) if text else []
        return self._awareness_tokens[file_path]

    def get_doc_tree(self, file_path: str) -> '_TreeNode':
        """TEDS 문서 구조 트리를 캐싱하여 반환합니다."""
        if file_path not in self._doc_trees:
            text = self.get_text(file_path)
            self._doc_trees[file_path] = _markdown_document_to_tree(text) if text else _TreeNode('doc')
        return self._doc_trees[file_path]

    def get_table_data(self, file_path: str) -> list[list[list[str]]]:
        """Markdown 테이블 데이터를 캐싱하여 반환합니다."""
        if file_path not in self._table_data:
            text = self.get_text(file_path)
            self._table_data[file_path] = _extract_markdown_tables(text) if text else []
        return self._table_data[file_path]

    def preload(self, file_paths: list[str]) -> None:
        for fp in file_paths:
            self.get_text(fp)
        logger.info(f"DocumentCache: {len(file_paths)}개 문서 프리로드 완료")

    def clear(self) -> None:
        """캐시를 초기화합니다."""
        self._texts.clear()
        self._tokens.clear()
        self._awareness_tokens.clear()
        self._doc_trees.clear()
        self._table_data.clear()
        logger.info("DocumentCache: 캐시가 초기화되었습니다.")


_doc_cache = DocumentCache()


# =============================================================================
# 전역 TF-IDF Vectorizer
# =============================================================================

_global_tfidf_vectorizer: TfidfVectorizer | None = None
_global_tfidf_matrix = None
_global_tfidf_file_index: dict[str, int] = {}


def fit_global_tfidf(file_paths: list[str]) -> None:
    """전체 문서 코퍼스에 대해 TF-IDF Vectorizer를 한 번만 fit합니다."""
    global _global_tfidf_vectorizer, _global_tfidf_matrix, _global_tfidf_file_index
    texts, valid_paths = [], []
    for fp in file_paths:
        text = _doc_cache.get_text(fp)
        if text and len(text.strip()) >= 10:
            texts.append(text)
            valid_paths.append(fp)
    if not texts:
        logger.warning("TF-IDF: 유효한 문서가 없어 Vectorizer를 초기화할 수 없습니다.")
        return
    logger.info(f"전역 TF-IDF Vectorizer 학습 중 ({len(texts)}개 문서)...")
    _global_tfidf_vectorizer = TfidfVectorizer()
    _global_tfidf_matrix = _global_tfidf_vectorizer.fit_transform(texts)
    _global_tfidf_file_index = {fp: i for i, fp in enumerate(valid_paths)}
    logger.info(f"전역 TF-IDF Vectorizer 학습 완료 (어휘 크기: {len(_global_tfidf_vectorizer.get_feature_names_out())})")


def _get_tfidf_vector(file_path: str):
    """파일의 TF-IDF 벡터를 반환합니다 (전역 vectorizer 사용)."""
    if _global_tfidf_vectorizer is None:
        return None
    if file_path in _global_tfidf_file_index:
        idx = _global_tfidf_file_index[file_path]
        return _global_tfidf_matrix[idx]
    text = _doc_cache.get_text(file_path)
    if text:
        return _global_tfidf_vectorizer.transform([text])
    return None


# =============================================================================
# 파일 로드
# =============================================================================

_FRONT_MATTER_RE = re.compile(r'\A---\s*\n.*?\n---\s*\n(.*)', re.DOTALL)


def load_text(file_path: str) -> str:
    """
    마크다운 파일을 읽어 본문만 반환합니다.
    YAML Front Matter(--- ... ---)가 있으면 제거합니다.
    """
    try:
        content = None
        last_error: Exception | None = None
        for encoding in ('utf-8-sig', 'utf-8', 'cp949'):
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError as e:
                last_error = e
        if content is None:
            raise last_error or UnicodeDecodeError('unknown', b'', 0, 1, 'unknown encoding error')

        if not content or not content.strip():
            logger.warning(f"{os.path.basename(file_path)} 파일이 비어있습니다.")
            return ""

        match = _FRONT_MATTER_RE.match(content)
        result = match.group(1).strip() if match else content.strip()

        if len(result) < 50:
            logger.warning(f"{os.path.basename(file_path)} 내용이 너무 짧습니다 ({len(result)}자)")
            logger.debug(f"  처음 200자: {result[:200]}")
        elif len(result) < 200:
            logger.info(f"{os.path.basename(file_path)} 길이: {len(result)}자")

        return result

    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        logger.debug(traceback.format_exc())
        return ""


# =============================================================================
# 한국어 토크나이저
# =============================================================================

def tokenize_korean(text: str) -> list[str]:
    """
    한국어 텍스트를 토큰 리스트로 변환합니다.
    kiwipiepy가 있으면 형태소 단위, 없으면 음절 단위로 분리합니다.
    """
    if KIWI_AVAILABLE:
        return [t.form for t in _kiwi.tokenize(text)]
    return list(text)


# =============================================================================
# 유사도 메트릭 계산 함수들
# =============================================================================

def _is_valid_text(text: str, min_len: int = 10) -> bool:
    return bool(text and len(text.strip()) >= min_len)


def _split_text_chunks(text: str, max_chars: int = 1500) -> list[str]:
    """긴 문서를 문단 경계 중심으로 모델 입력 가능한 chunk로 나눕니다."""
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
    if not paragraphs:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append('\n\n'.join(current))
                current = []
                current_len = 0
            chunks.extend(paragraph[i:i + max_chars] for i in range(0, len(paragraph), max_chars))
            continue

        next_len = current_len + len(paragraph) + (2 if current else 0)
        if current and next_len > max_chars:
            chunks.append('\n\n'.join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len = next_len

    if current:
        chunks.append('\n\n'.join(current))
    return chunks


def _aligned_chunk_pairs(chunks1: list[str], chunks2: list[str]) -> tuple[list[str], list[str], list[float]]:
    """서로 다른 chunk 개수를 상대 위치 기준으로 정렬합니다."""
    pair_count = max(len(chunks1), len(chunks2))
    if pair_count == 0:
        return [], [], []

    left: list[str] = []
    right: list[str] = []
    weights: list[float] = []
    for i in range(pair_count):
        idx1 = min(len(chunks1) - 1, int(i * len(chunks1) / pair_count))
        idx2 = min(len(chunks2) - 1, int(i * len(chunks2) / pair_count))
        c1 = chunks1[idx1]
        c2 = chunks2[idx2]
        left.append(c1)
        right.append(c2)
        weights.append(max(1.0, (len(c1) + len(c2)) / 2.0))
    return left, right, weights


def calculate_vocab_overlap_f1(
    text1: str, text2: str,
    file1: str | None = None, file2: str | None = None,
) -> float:
    """TF-IDF 이진 벡터 기반 어휘 겹침 F1을 계산합니다. 전역 Vectorizer 우선 사용."""
    if not _is_valid_text(text1) or not _is_valid_text(text2):
        logger.warning(
            f"vocab_overlap_F1 계산 실패 - "
            f"text1={len(text1) if text1 else 0}자, text2={len(text2) if text2 else 0}자"
        )
        return 0.0

    try:
        # 전역 vectorizer 사용
        if _global_tfidf_vectorizer is not None and file1 and file2:
            vec1, vec2 = _get_tfidf_vector(file1), _get_tfidf_vector(file2)
            if vec1 is not None and vec2 is not None:
                binary1 = (vec1 > 0).astype(int).toarray()[0]
                binary2 = (vec2 > 0).astype(int).toarray()[0]
                result = float(f1_score(binary1, binary2, average='binary'))
                if result == 0.0:
                    logger.warning(f"vocab_overlap_F1=0 (전역 vectorizer)")
                return result

        # fallback: 로컬 vectorizer
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform([text1, text2])

        if tfidf_matrix.shape[1] == 0:
            logger.warning("vocab_overlap_F1 — TF-IDF 벡터가 비어있음")
            return 0.0

        binary_matrix = (tfidf_matrix > 0).astype(int)
        result = float(f1_score(
            binary_matrix[0].toarray()[0],
            binary_matrix[1].toarray()[0],
            average='binary',
        ))
        return result

    except Exception as e:
        logger.error(f"Error calculating vocab_overlap_F1: {e}")
        logger.debug(traceback.format_exc())
        return 0.0


def calculate_rouge_scores(reference: str, candidate: str) -> dict:
    """ROUGE-1, ROUGE-2, ROUGE-L F1을 반환합니다."""
    empty = {'rouge1': 0.0, 'rouge2': 0.0, 'rougeL': 0.0}

    if not _is_valid_text(reference) or not _is_valid_text(candidate):
        logger.warning(
            f"ROUGE 계산 실패 - "
            f"reference={len(reference) if reference else 0}자, "
            f"candidate={len(candidate) if candidate else 0}자"
        )
        return empty

    try:
        scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL'], use_stemmer=False)
        scores = scorer.score(reference, candidate)
        result = {
            'rouge1': float(scores['rouge1'].fmeasure),
            'rouge2': float(scores['rouge2'].fmeasure),
            'rougeL': float(scores['rougeL'].fmeasure),
        }

        if all(v == 0.0 for v in result.values()):
            logger.warning("모든 ROUGE 점수가 0입니다.")
            logger.debug(
                f"ROUGE-1 recall={scores['rouge1'].recall:.4f}, "
                f"precision={scores['rouge1'].precision:.4f}"
            )

        return result

    except Exception as e:
        logger.error(f"Error calculating ROUGE scores: {e}")
        logger.debug(traceback.format_exc())
        return empty


def calculate_bleu_score(
    reference: str, candidate: str,
    ref_tokens: list[str] | None = None,
    cand_tokens: list[str] | None = None,
) -> float:
    """한국어 BLEU 점수를 계산합니다. 캐시된 토큰을 받을 수 있습니다.

    n-gram이 일부 매칭되지 않을 때 BLEU-3/4가 과도하게 0으로 떨어지는 문제를
    줄이기 위해 NLTK smoothing을 적용합니다.
    """
    if not reference or not candidate:
        return 0.0
    try:
        if ref_tokens is None:
            ref_tokens = tokenize_korean(reference)
        if cand_tokens is None:
            cand_tokens = tokenize_korean(candidate)
        if not ref_tokens or not cand_tokens:
            return 0.0

        weights = [
            (1, 0, 0, 0),
            (0.5, 0.5, 0, 0),
            (0.33, 0.33, 0.33, 0),
            (0.25, 0.25, 0.25, 0.25),
        ]
        scores = [
            sentence_bleu(
                [ref_tokens], cand_tokens,
                weights=w,
                smoothing_function=_BLEU_SMOOTHER,
            )
            for w in weights
        ]
        return float(sum(scores) / len(scores))
    except Exception as e:
        logger.error(f"Error calculating BLEU score: {e}")
        return 0.0


def calculate_tfidf_similarity(
    text1: str, text2: str,
    file1: str | None = None, file2: str | None = None,
) -> float:
    """TF-IDF 코사인 유사도를 반환합니다. 전역 Vectorizer 우선 사용."""
    if not text1 or not text2:
        return 0.0
    try:
        # 전역 vectorizer 사용
        if _global_tfidf_vectorizer is not None and file1 and file2:
            vec1, vec2 = _get_tfidf_vector(file1), _get_tfidf_vector(file2)
            if vec1 is not None and vec2 is not None:
                return float(cosine_similarity(vec1, vec2)[0][0])
        # fallback
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform([text1, text2])
        return float(cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0])
    except Exception as e:
        logger.error(f"Error calculating TF-IDF similarity: {e}")
        return 0.0


def calculate_bertscore(text1: str, text2: str) -> float:
    """BERTScore F1을 반환합니다 (BERTScorer 객체 재사용)."""
    if not _is_valid_text(text1) or not _is_valid_text(text2):
        return _metric_failure(
            "BERTScore",
            f"text1={len(text1) if text1 else 0}자, text2={len(text2) if text2 else 0}자",
        )
    try:
        scorer = get_bert_scorer()
        chunks1 = _split_text_chunks(text1)
        chunks2 = _split_text_chunks(text2)
        refs, cands, weights = _aligned_chunk_pairs(chunks1, chunks2)
        if not refs or not cands:
            return _metric_failure("BERTScore", "chunk가 비어있음")
        _, _, f1_scores = scorer.score(refs, cands)
        scores = f1_scores.detach().cpu().numpy()
        return float(np.average(scores, weights=np.array(weights)))
    except Exception as e:
        return _metric_failure("BERTScore", "예외 발생", e)


def calculate_sts(text1: str, text2: str) -> float:
    """STS(문장 임베딩) 코사인 유사도를 반환합니다."""
    if not _is_valid_text(text1) or not _is_valid_text(text2):
        return _metric_failure(
            "STS",
            f"text1={len(text1) if text1 else 0}자, text2={len(text2) if text2 else 0}자",
        )
    try:
        chunks1 = _split_text_chunks(text1)
        chunks2 = _split_text_chunks(text2)
        if not chunks1 or not chunks2:
            return _metric_failure("STS", "chunk가 비어있음")

        model = get_sts_model()
        emb1 = model.encode(chunks1, convert_to_tensor=True)
        emb2 = model.encode(chunks2, convert_to_tensor=True)
        sim_matrix = util.pytorch_cos_sim(emb1, emb2)

        best_1_to_2 = sim_matrix.max(dim=1).values.detach().cpu().numpy()
        weights_1 = np.array([max(1, len(chunk)) for chunk in chunks1], dtype=float)
        score_1_to_2 = float(np.average(best_1_to_2, weights=weights_1))

        best_2_to_1 = sim_matrix.max(dim=0).values.detach().cpu().numpy()
        weights_2 = np.array([max(1, len(chunk)) for chunk in chunks2], dtype=float)
        score_2_to_1 = float(np.average(best_2_to_1, weights=weights_2))

        return float((score_1_to_2 + score_2_to_1) / 2.0)
    except Exception as e:
        return _metric_failure("STS", "예외 발생", e)


def calculate_earth_mover_distance(embeddings1: np.ndarray, embeddings2: np.ndarray) -> float:
    """Hungarian algorithm 기반 EMD를 코사인 거리로 계산합니다 (유사도 0~1 반환)."""
    if len(embeddings1) == 0 or len(embeddings2) == 0:
        return 0.0
    try:
        emb1 = np.atleast_2d(np.array(embeddings1))
        emb2 = np.atleast_2d(np.array(embeddings2))
        dist_matrix = cdist(emb1, emb2, metric='cosine')
        dist_matrix = np.nan_to_num(dist_matrix, nan=1.0, posinf=1.0, neginf=0.0)
        row_idx, col_idx = linear_sum_assignment(dist_matrix)
        min_cost = dist_matrix[row_idx, col_idx].sum()
        num_pairs = min(len(emb1), len(emb2))
        avg_cost = min_cost / num_pairs if num_pairs > 0 else 2.0
        return float(max(0.0, min(1.0, 1.0 - avg_cost / 2.0)))
    except Exception as e:
        logger.error(f"Earth Mover Distance 계산 오류: {e}")
        return 0.0


def calculate_moverscore(text1: str, text2: str) -> float:
    """
    MoverScore를 계산합니다.
    라이브러리가 없으면 STS 임베딩 + EMD로 근사합니다.
    참고: https://arxiv.org/abs/1909.02622
    """
    if not _is_valid_text(text1) or not _is_valid_text(text2):
        return _metric_failure(
            "MoverScore",
            f"text1={len(text1) if text1 else 0}자, text2={len(text2) if text2 else 0}자",
        )

    def split_sentences(text: str) -> list[str]:
        parts = [s.strip() for s in re.split(r'(?:[.!?。]\s+|(?<=다\.)\s+|\n+)', text) if s.strip()]
        return parts or _split_text_chunks(text)

    try:
        if MOVERSCORE_AVAILABLE:
            ms_model, ms_tokenizer, ms_idf = get_moverscore_model()
            try:
                if ms_model is not None:
                    sents1, sents2 = split_sentences(text1), split_sentences(text2)
                    with torch.no_grad():
                        score = word_mover_score(
                            ms_model, ms_tokenizer, sents1, sents2,
                            idf_dict_ref=ms_idf, idf_dict_hyp=ms_idf,
                            device=_get_device(),
                            batch_size=1,
                        )
                    return float(np.mean(score) if isinstance(score, list) else score)
            except Exception as e:
                logger.warning(f"MoverScore 라이브러리 사용 실패, fallback 사용: {e}")

        # fallback: STS + EMD
        sents1, sents2 = _split_text_chunks(text1), _split_text_chunks(text2)
        sts = get_sts_model()
        emb1 = sts.encode(sents1, convert_to_numpy=True)
        emb2 = sts.encode(sents2, convert_to_numpy=True)

        if emb1.shape[0] == 0 or emb2.shape[0] == 0:
            return _metric_failure("MoverScore", "fallback 임베딩이 비어있음")

        similarity = calculate_earth_mover_distance(emb1, emb2)
        return 0.0 if (np.isnan(similarity) or np.isinf(similarity)) else float(similarity)

    except Exception as e:
        return _metric_failure("MoverScore", "예외 발생", e)


# =============================================================================
# 문서 구조 분석: MDEval + PubTabNet/TEDS 기반
# =============================================================================

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
_CODE_FENCE_RE = re.compile(r'```[\s\S]*?```')
_TABLE_SEPARATOR_RE = re.compile(r'^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$')
_LIST_ITEM_RE = re.compile(r'^(\s*)(?:[-*+]|\d+[\.)])\s+(.+)$')


class _TreeNode:
    """TEDS 계산을 위한 경량 ordered tree 노드."""

    __slots__ = ('label', 'children', '_size')

    def __init__(self, label: str, children: list['_TreeNode'] | None = None):
        self.label = label
        self.children = children or []
        self._size: int | None = None

    @property
    def size(self) -> int:
        """서브트리 크기를 처음 호출 시에만 계산하고 이후 캐싱합니다."""
        if self._size is None:
            self._size = 1 + sum(c.size for c in self.children)
        return self._size


def _strip_code_fences(markdown_text: str) -> str:
    """마크다운 구조 분석 시 코드 펜스 내부 문법 오탐을 줄입니다."""
    return _CODE_FENCE_RE.sub('\n<code_block/>\n', markdown_text or '')


def _levenshtein_sequence_distance(seq1: list[str], seq2: list[str]) -> int:
    """토큰 시퀀스 간 Levenshtein edit distance."""
    m, n = len(seq1), len(seq2)
    if m == 0:
        return n
    if n == 0:
        return m

    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        a = seq1[i - 1]
        for j in range(1, n + 1):
            cost = 0 if a == seq2[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def _normalized_edit_similarity(seq1: list[str], seq2: list[str]) -> float:
    """1 - edit_distance / max_len 형태의 정규화 유사도."""
    denom = max(len(seq1), len(seq2))
    if denom == 0:
        return 1.0
    dist = _levenshtein_sequence_distance(seq1, seq2)
    return float(max(0.0, 1.0 - dist / denom))


def _split_markdown_table_row(line: str) -> list[str]:
    """간단한 Markdown pipe table 행을 셀 목록으로 분리합니다."""
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|'):
        s = s[:-1]
    return [cell.strip() for cell in s.split('|')]


def _is_table_separator(line: str) -> bool:
    return bool(_TABLE_SEPARATOR_RE.match(line.strip()))


def _extract_markdown_tables(markdown_text: str) -> list[list[list[str]]]:
    """Markdown pipe table을 행/셀 배열로 추출합니다."""
    lines = _strip_code_fences(markdown_text).splitlines()
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            # 구분선 행은 제외합니다.
            rows = [row for row in current if not all(re.fullmatch(r':?-{3,}:?', c.replace(' ', '')) for c in row)]
            if rows:
                tables.append(rows)
        current = []

    for line in lines:
        stripped = line.strip()
        if '|' in stripped and not stripped.startswith('```'):
            cells = _split_markdown_table_row(stripped)
            if len(cells) >= 2:
                current.append(cells)
                continue
        flush()
    flush()
    return tables


def _markdown_to_awareness_tokens(markdown_text: str) -> list[str]:
    """MDEval의 Markdown Awareness 취지를 반영한 구조 토큰 시퀀스 생성.

    MDEval은 Markdown 출력 능력을 문서 구조와 가독성 관점에서 평가한다.
    여기서는 LLM 산출 ADR의 본문 의미를 제외하고, Markdown 구조 요소를
    HTML-like 토큰 시퀀스로 변환한 뒤 정규화 edit similarity를 계산한다.
    """
    text = _strip_code_fences(markdown_text)
    tokens: list[str] = []
    in_table = False
    in_ul_stack: list[int] = []
    in_ol_stack: list[int] = []

    def close_lists() -> None:
        nonlocal in_ul_stack, in_ol_stack
        while in_ul_stack:
            tokens.append('</ul>')
            in_ul_stack.pop()
        while in_ol_stack:
            tokens.append('</ol>')
            in_ol_stack.pop()

    for raw in text.splitlines():
        line = raw.rstrip('\n')
        stripped = line.strip()
        if not stripped:
            if in_table:
                tokens.append('</table>')
                in_table = False
            close_lists()
            continue

        if stripped == '<code_block/>':
            if in_table:
                tokens.append('</table>')
                in_table = False
            close_lists()
            tokens.extend(['<pre>', '</pre>'])
            continue

        heading = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading:
            if in_table:
                tokens.append('</table>')
                in_table = False
            close_lists()
            level = len(heading.group(1))
            tokens.extend([f'<h{level}>', f'</h{level}>'])
            continue

        if '|' in stripped:
            cells = _split_markdown_table_row(stripped)
            if len(cells) >= 2:
                close_lists()
                if not in_table:
                    tokens.append('<table>')
                    in_table = True
                if _is_table_separator(stripped):
                    tokens.append('<thead-sep/>')
                else:
                    tokens.append('<tr>')
                    tokens.extend(['<td></td>'] * len(cells))
                    tokens.append('</tr>')
                continue
        if in_table:
            tokens.append('</table>')
            in_table = False

        li = _LIST_ITEM_RE.match(line)
        if li:
            indent = len(li.group(1).replace('\t', '    ')) // 2
            ordered = bool(re.match(r'^\s*\d+[\.)]\s+', line))
            if ordered:
                while len(in_ol_stack) <= indent:
                    tokens.append('<ol>')
                    in_ol_stack.append(len(in_ol_stack))
                while len(in_ol_stack) > indent + 1:
                    tokens.append('</ol>')
                    in_ol_stack.pop()
                tokens.extend(['<li>', '</li>'])
            else:
                while len(in_ul_stack) <= indent:
                    tokens.append('<ul>')
                    in_ul_stack.append(len(in_ul_stack))
                while len(in_ul_stack) > indent + 1:
                    tokens.append('</ul>')
                    in_ul_stack.pop()
                tokens.extend(['<li>', '</li>'])
            continue

        close_lists()
        # 문단은 내용 길이나 어휘가 아니라 구조적 존재만 반영합니다.
        tokens.extend(['<p>', '</p>'])

    if in_table:
        tokens.append('</table>')
    close_lists()
    return tokens


def calculate_markdown_awareness_similarity(
    text1: str, text2: str,
    *,
    tokens1: list[str] | None = None,
    tokens2: list[str] | None = None,
) -> float:
    """MDEval-style Markdown Awareness 유사도.

    Markdown 구조 토큰을 대상으로 정규화 edit similarity를 계산합니다.
    사전 계산된 토큰 시퀀스(tokens1/tokens2)가 있으면 재사용합니다.
    """
    t1 = tokens1 if tokens1 is not None else _markdown_to_awareness_tokens(text1)
    t2 = tokens2 if tokens2 is not None else _markdown_to_awareness_tokens(text2)
    return _normalized_edit_similarity(t1, t2)


def _markdown_table_to_tree(table: list[list[str]]) -> _TreeNode:
    """Markdown table을 PubTabNet/TEDS 방식에 맞춘 HTML-like tree로 변환."""
    children: list[_TreeNode] = []
    for row_idx, row in enumerate(table):
        cell_tag = 'th' if row_idx == 0 else 'td'
        row_children = [_TreeNode(cell_tag) for _ in row]
        children.append(_TreeNode('tr', row_children))
    return _TreeNode('table', children)


def _markdown_document_to_tree(markdown_text: str) -> _TreeNode:
    """Markdown 문서를 ordered tree로 변환합니다.

    PubTabNet/TEDS가 HTML tree의 edit distance로 표 구조를 평가한 점을
    문서 전체 Markdown 구조에 확장 적용합니다. 텍스트 내용은 제외하고
    헤딩, 섹션, 표, 리스트, 코드블록, 문단의 구조만 반영합니다.
    """
    root = _TreeNode('doc')
    stack: list[tuple[int, _TreeNode]] = [(0, root)]
    lines = _strip_code_fences(markdown_text).splitlines()
    i = 0

    def current_parent() -> _TreeNode:
        return stack[-1][1]

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if stripped == '<code_block/>':
            current_parent().children.append(_TreeNode('pre'))
            i += 1
            continue

        heading = re.match(r'^(#{1,6})\s+(.+)$', stripped)
        if heading:
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            node = _TreeNode(f'h{level}')
            stack[-1][1].children.append(node)
            stack.append((level, node))
            i += 1
            continue

        if '|' in stripped:
            table_lines: list[str] = []
            j = i
            while j < len(lines) and '|' in lines[j].strip():
                cells = _split_markdown_table_row(lines[j].strip())
                if len(cells) < 2:
                    break
                table_lines.append(lines[j].strip())
                j += 1
            if len(table_lines) >= 2:
                rows = [_split_markdown_table_row(x) for x in table_lines if not _is_table_separator(x)]
                if rows:
                    current_parent().children.append(_markdown_table_to_tree(rows))
                    i = j
                    continue

        li = _LIST_ITEM_RE.match(line)
        if li:
            ordered = bool(re.match(r'^\s*\d+[\.)]\s+', line))
            list_tag = 'ol' if ordered else 'ul'
            list_node = _TreeNode(list_tag)
            while i < len(lines):
                m = _LIST_ITEM_RE.match(lines[i])
                if not m:
                    break
                curr_ordered = bool(re.match(r'^\s*\d+[\.)]\s+', lines[i]))
                if curr_ordered != ordered:
                    break
                list_node.children.append(_TreeNode('li'))
                i += 1
            current_parent().children.append(list_node)
            continue

        current_parent().children.append(_TreeNode('p'))
        i += 1

    return root


def _tree_size(node: _TreeNode) -> int:
    return node.size


def _tree_edit_distance(
    node1: _TreeNode, node2: _TreeNode,
    _memo: dict[tuple[int, int], int] | None = None,
) -> int:
    """Ordered tree edit distance의 동적계획 구현 (메모이제이션 적용).

    PubTabNet/TEDS의 핵심 아이디어인 tree edit distance 기반 구조 비교를
    ADR Markdown 구조에 적용하기 위한 구현입니다. 노드 삽입/삭제 비용은
    서브트리 크기, 노드 치환 비용은 label 불일치 시 1로 둡니다.
    _memo는 한 번의 비교 호출 내에서 동일 (node1, node2) 쌍의 재계산을 방지합니다.
    """
    if _memo is None:
        _memo = {}
    key = (id(node1), id(node2))
    if key in _memo:
        return _memo[key]

    update_cost = 0 if node1.label == node2.label else 1
    c1, c2 = node1.children, node2.children
    m, n = len(c1), len(c2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + c1[i - 1].size
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + c2[j - 1].size
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(
                dp[i - 1][j] + c1[i - 1].size,
                dp[i][j - 1] + c2[j - 1].size,
                dp[i - 1][j - 1] + _tree_edit_distance(c1[i - 1], c2[j - 1], _memo),
            )
    result = update_cost + dp[m][n]
    _memo[key] = result
    return result


def _tree_edit_similarity(node1: _TreeNode, node2: _TreeNode) -> float:
    denom = max(node1.size, node2.size)
    if denom == 0:
        return 1.0
    dist = _tree_edit_distance(node1, node2, {})
    return float(max(0.0, 1.0 - dist / denom))


def calculate_document_teds_similarity(
    text1: str, text2: str,
    *,
    tree1: _TreeNode | None = None,
    tree2: _TreeNode | None = None,
) -> float:
    """TEDS-style 문서 구조 유사도.

    사전 변환된 트리(tree1/tree2)가 있으면 재사용합니다.
    """
    t1 = tree1 if tree1 is not None else _markdown_document_to_tree(text1)
    t2 = tree2 if tree2 is not None else _markdown_document_to_tree(text2)
    return _tree_edit_similarity(t1, t2)


def calculate_table_teds_similarity(
    text1: str, text2: str,
    *,
    tables1: list[list[list[str]]] | None = None,
    tables2: list[list[list[str]]] | None = None,
) -> float:
    """PubTabNet/TEDS-style 표 구조 유사도.

    표가 양쪽 모두 없으면 구조 점수를 과대평가하지 않도록 NaN을 반환합니다.
    한쪽에만 표가 있으면 0.0입니다. 여러 표가 있으면 양방향 최고 매칭을
    평균하여 표 추가/누락이 한쪽 방향으로만 유리하게 평가되지 않도록 합니다.

    사전 추출된 테이블 데이터(tables1/tables2)가 있으면 재사용합니다.
    """
    t1 = tables1 if tables1 is not None else _extract_markdown_tables(text1)
    t2 = tables2 if tables2 is not None else _extract_markdown_tables(text2)
    if not t1 and not t2:
        return float('nan')
    if not t1 or not t2:
        return 0.0

    trees1 = [_markdown_table_to_tree(t) for t in t1]
    trees2 = [_markdown_table_to_tree(t) for t in t2]
    scores_1_to_2 = [max(_tree_edit_similarity(tr1, tr2) for tr2 in trees2) for tr1 in trees1]
    scores_2_to_1 = [max(_tree_edit_similarity(tr2, tr1) for tr1 in trees1) for tr2 in trees2]
    scores = scores_1_to_2 + scores_2_to_1
    return float(np.mean(scores)) if scores else float('nan')


def calculate_document_structure_similarity(
    text1: str, text2: str,
    *,
    file1: str | None = None, file2: str | None = None,
) -> dict:
    """MDEval + PubTabNet/TEDS 기반 구조 유사도를 반환합니다.

    다음 연구 기반 지표를 사용합니다.
      1) markdown_awareness_similarity: MDEval의 Markdown Awareness 취지
      2) teds_document_structure_similarity: tree edit distance 기반 문서 구조 유사도
      3) teds_table_structure_similarity: PubTabNet/TEDS 방식의 표 구조 유사도

    file1/file2가 주어지면 DocumentCache의 캐싱 결과를 활용하여 중복 연산을 제거합니다.
    """
    # 캐시 활용: file path가 있으면 사전 계산된 결과를 재사용
    if file1 and file2:
        tokens1 = _doc_cache.get_awareness_tokens(file1)
        tokens2 = _doc_cache.get_awareness_tokens(file2)
        tree1   = _doc_cache.get_doc_tree(file1)
        tree2   = _doc_cache.get_doc_tree(file2)
        tables1 = _doc_cache.get_table_data(file1)
        tables2 = _doc_cache.get_table_data(file2)
    else:
        tokens1 = tokens2 = None
        tree1 = tree2 = None
        tables1 = tables2 = None

    md_awareness = calculate_markdown_awareness_similarity(
        text1, text2, tokens1=tokens1, tokens2=tokens2,
    )
    doc_teds = calculate_document_teds_similarity(
        text1, text2, tree1=tree1, tree2=tree2,
    )
    table_teds = calculate_table_teds_similarity(
        text1, text2, tables1=tables1, tables2=tables2,
    )

    weighted_items = [
        (md_awareness, 0.40),
        (doc_teds, 0.40),
        (table_teds, 0.20),
    ]
    valid = [(score, weight) for score, weight in weighted_items if pd.notna(score)]
    if valid:
        weight_sum = sum(weight for _, weight in valid)
        overall = sum(score * weight for score, weight in valid) / weight_sum
    else:
        overall = float('nan')

    return {
        'markdown_awareness_similarity': md_awareness,
        'teds_document_structure_similarity': doc_teds,
        'teds_table_structure_similarity': table_teds,
        'overall_document_structure_similarity': overall,
    }


# =============================================================================
# 종합 점수 계산 (그룹별 가중 평균)
# =============================================================================

_STRUCTURE_METRIC_COLS: list[str] = [
    # MDEval: Markdown Awareness based on normalized edit similarity
    'markdown_awareness_similarity',
    # PubTabNet/TEDS: tree edit distance based document/table structure similarity
    'teds_document_structure_similarity',
    'teds_table_structure_similarity',
    'overall_document_structure_similarity',
]

# 점수 계산 전용: overall_document_structure_similarity는 나머지 세 지표의
# 가중 평균이므로 함께 평균하면 이중 계산이 발생한다. 출력 컬럼(_STRUCTURE_METRIC_COLS)과
# 점수 컬럼을 분리하여 compute_overall_score에서는 이 목록만 사용한다.
_STRUCTURE_SCORE_COLS: list[str] = [
    'markdown_awareness_similarity',
    'teds_document_structure_similarity',
    'teds_table_structure_similarity',
]

_METRIC_GROUPS: dict[str, tuple[float, list[str]]] = {
    'lexical':   (0.20, ['f1_score', 'rouge1', 'rouge2', 'rougeL', 'bleu_score', 'tfidf_similarity']),
    'semantic':  (0.45, ['bertscore', 'sts_score', 'moverscore']),
    'structure': (0.35, _STRUCTURE_SCORE_COLS),
}


def compute_overall_score(row: pd.Series) -> float:
    """lexical(20%) + semantic(45%) + structure(35%) 가중 평균.

    값이 모두 NaN인 그룹은 분모에서 제외하여 가중치를 재정규화합니다.
    (예: structure 전 컬럼이 NaN이면 lexical 20% + semantic 45% = 65%로 정규화)
    """
    total = 0.0
    weight_sum = 0.0
    for weight, cols in _METRIC_GROUPS.values():
        vals = [row[c] for c in cols if c in row and pd.notna(row[c])]
        if vals:
            total += weight * float(np.mean(vals))
            weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


# =============================================================================
# 파일명 파싱
# =============================================================================

def extract_document_info(filename: str) -> tuple[str | None, str | None, str | None]:
    """
    파일명에서 (document_id, model_token, doc_type)을 추출합니다.

    파싱 전략:
        파일명을 '_'로 분리한 뒤 뒤에서부터 확인합니다.
        - 마지막 토큰이 doc_type이면 제거
        - 남은 부분에서 _MODEL_REGISTRY에 등록된 가장 긴 연속 토큰 조합을 model_token으로 인식
          (예: 'qwen3', '6plus' → 'qwen3_6plus')
        - 나머지가 document_id

    지원 예시:
        1020200184565B1_1_2_gemini_ADR.md       → ('1020200184565B1_1_2', 'gemini', 'ADR')
        1020200184565B1_1_2_claude_PRD.md       → ('1020200184565B1_1_2', 'claude', 'PRD')
        1020200184565B1_1_2_qwen3_6plus_ADR.md  → ('1020200184565B1_1_2', 'qwen3_6plus', 'ADR')
        1020200184565B1_1_2_chatgpt_TestPlan.md → ('1020200184565B1_1_2', 'chatgpt', 'TestPlan')
    """
    base  = os.path.splitext(filename)[0]
    parts = base.split('_')

    # 1. 마지막 토큰이 doc_type인지 확인합니다.
    #    대소문자 차이로 TestPlan/testplan 등이 누락되지 않도록 정규화합니다.
    doc_type_lookup = {dt.lower(): dt for dt in _DOC_TYPES}
    if parts[-1].lower() in doc_type_lookup:
        doc_type   = doc_type_lookup[parts[-1].lower()]
        remaining  = parts[:-1]
    else:
        doc_type   = None
        remaining  = parts

    # 2. remaining 뒤에서부터 가장 긴 model_token 조합을 탐색
    #    (예: ['...', 'qwen3', '6plus'] → 'qwen3_6plus' 우선 매칭)
    model_token = None
    model_end   = len(remaining)  # model 토큰이 끝나는 인덱스 (exclusive)

    for length in range(min(4, len(remaining)), 0, -1):  # 최대 4토큰 조합까지 허용
        candidate = '_'.join(remaining[-(length):]).lower()
        if candidate in _ALL_MODEL_TOKENS:
            model_token = normalize_model_token(candidate)
            model_end   = len(remaining) - length
            break

    if model_token is None:
        return None, None, None

    document_id = '_'.join(remaining[:model_end]) or None
    return document_id, model_token, doc_type


# =============================================================================
# 단일 기준 모델 실행
# =============================================================================

def run_for_reference(
    reference_token: str,
    document_groups: dict[str, dict[str, dict[str, str]]],
    compare_tokens: set[str] | None = None,
) -> list[dict]:
    """
    주어진 기준 모델(reference_token)을 기준으로
    나머지 모델과 쌍별 유사도를 계산하고 결과 행 목록을 반환합니다.
    DocumentCache를 활용하여 중복 연산을 제거합니다.

    Args:
        compare_tokens: 비교 대상 모델 토큰 집합. None이면 모든 모델과 비교.
    """
    ref_display = display_name(reference_token)
    results: list[dict] = []

    for document_id, doc_type_dict in document_groups.items():
        logger.info(f"{'='*80}")
        logger.info(f"[기준: {ref_display}] Processing document: {document_id}")

        for doc_type in _DOC_TYPES:
            if doc_type not in doc_type_dict:
                continue

            model_files_dict = doc_type_dict[doc_type]
            logger.info(f"  Processing document type: {doc_type}")

            ref_file = model_files_dict.get(reference_token)
            if not ref_file:
                logger.info(f"  Skipping {document_id} ({doc_type}): "
                            f"{ref_display} 파일 없음")
                continue

            comparison_tokens = [
                token for token in model_files_dict
                if token != reference_token
                and (compare_tokens is None or token in compare_tokens)
            ]
            if not comparison_tokens:
                logger.info(f"  Skipping {document_id} ({doc_type}): 비교 대상 모델 없음")
                continue

            # 캐시에서 기준 텍스트/토큰 로드
            ref_text = _doc_cache.get_text(ref_file)
            if not ref_text:
                logger.warning(f"  Skipping {document_id} ({doc_type}): {ref_display} 파일 비어있음")
                continue

            ref_tokens = _doc_cache.get_tokens(ref_file)

            logger.info(f"  {ref_display} 텍스트 길이: {len(ref_text)}자")
            if len(ref_text) < 100:
                logger.warning(f"  {ref_display} 텍스트가 너무 짧습니다!")
            logger.info(f"  비교 모델: {', '.join(display_name(t) for t in comparison_tokens)}")

            for comp_token in comparison_tokens:
                comp_file = model_files_dict[comp_token]
                comp_text = _doc_cache.get_text(comp_file)
                if not comp_text:
                    logger.info(f"    - Skipping {display_name(comp_token)}: Empty file")
                    continue

                comp_display = display_name(comp_token)
                logger.info(f"    - {comp_display} vs {ref_display} "
                            f"(텍스트 길이: {len(comp_text)}자)")
                if len(comp_text) < 100:
                    logger.warning(f"      {comp_display} 텍스트가 너무 짧습니다!")

                # 캐시된 토큰 사용
                comp_tokens = _doc_cache.get_tokens(comp_file)

                rouge         = calculate_rouge_scores(ref_text, comp_text)

                # 캐시된 구조 분석 결과 사용 (awareness tokens, doc tree, table data)
                structure_sim = calculate_document_structure_similarity(
                    ref_text, comp_text,
                    file1=ref_file, file2=comp_file,
                )

                # Semantic metric은 reference/candidate 방향을 보존해 캐시합니다.
                bert_key = ('bertscore', ref_file, comp_file)
                mover_key = ('moverscore', ref_file, comp_file)
                if bert_key in _pairwise_metric_cache:
                    bertscore_val = _pairwise_metric_cache[bert_key]
                    logger.debug("    BERTScore cache hit: %s -> %s",
                                 os.path.basename(ref_file), os.path.basename(comp_file))
                else:
                    bertscore_val = calculate_bertscore(ref_text, comp_text)
                    _pairwise_metric_cache[bert_key] = bertscore_val

                if mover_key in _pairwise_metric_cache:
                    moverscore_val = _pairwise_metric_cache[mover_key]
                    logger.debug("    MoverScore cache hit: %s -> %s",
                                 os.path.basename(ref_file), os.path.basename(comp_file))
                else:
                    moverscore_val = calculate_moverscore(ref_text, comp_text)
                    _pairwise_metric_cache[mover_key] = moverscore_val

                sts_key = ('sts', ref_file, comp_file)
                if sts_key in _pairwise_metric_cache:
                    sts_val = _pairwise_metric_cache[sts_key]
                    logger.debug("    STS cache hit: %s -> %s",
                                 os.path.basename(ref_file), os.path.basename(comp_file))
                else:
                    sts_val = calculate_sts(ref_text, comp_text)
                    _pairwise_metric_cache[sts_key] = sts_val

                results.append({
                    'document_id':      document_id,
                    'doc_type':         doc_type,
                    'reference_model':  reference_token,
                    'comparison_model': comp_token,
                    # ── lexical ───────────────────────────────────────────────
                    'f1_score':         calculate_vocab_overlap_f1(
                                            ref_text, comp_text,
                                            file1=ref_file, file2=comp_file),
                    'rouge1':           rouge['rouge1'],
                    'rouge2':           rouge['rouge2'],
                    'rougeL':           rouge['rougeL'],
                    'bleu_score':       calculate_bleu_score(
                                            ref_text, comp_text,
                                            ref_tokens=ref_tokens, cand_tokens=comp_tokens),
                    'tfidf_similarity': calculate_tfidf_similarity(
                                            ref_text, comp_text,
                                            file1=ref_file, file2=comp_file),
                    # ── semantic ──────────────────────────────────────────────
                    'bertscore':        bertscore_val,
                    'sts_score':        sts_val,
                    'moverscore':       moverscore_val,
                    'bertscore_status':  'ok' if pd.notna(bertscore_val) else 'failed',
                    'sts_status':        'ok' if pd.notna(sts_val) else 'failed',
                    'moverscore_status': 'ok' if pd.notna(moverscore_val) else 'failed',
                    # ── structure ─────────────────────────────────────────────
                    **{k: structure_sim[k] for k in _STRUCTURE_METRIC_COLS},
                })

    return results


# =============================================================================
# 결과 출력 및 저장
# =============================================================================

def _print_stats(df: pd.DataFrame, ref_token: str, all_numeric_cols: list[str]) -> None:
    """단일 기준 모델에 대한 통계를 출력합니다."""
    ref_display = display_name(ref_token)
    vs_label    = f"vs {ref_display}"
    models      = sorted(df['comparison_model'].unique())

    def _log_full_stats(sub: pd.DataFrame, indent: str) -> None:
        """모델별로 모든 수치 컬럼의 평균/표준편차를 출력합니다."""
        for token in models:
            s = sub[sub['comparison_model'] == token]
            if len(s) == 0:
                continue
            logger.info(f"{indent}{display_name(token)} {vs_label}:")
            for col in all_numeric_cols:
                if col in s.columns:
                    logger.info(f"{indent}  {col}: 평균={s[col].mean():.4f}, "
                                f"표준편차={s[col].std():.4f}")

    def _log_overall_stats(sub: pd.DataFrame, indent: str) -> None:
        """모델별 overall_score 평균/표준편차만 한 줄로 출력합니다."""
        for token in models:
            s = sub[sub['comparison_model'] == token]
            if len(s) == 0:
                continue
            logger.info(f"{indent}{display_name(token)} {vs_label}: "
                        f"평균={s['overall_score'].mean():.4f}, "
                        f"표준편차={s['overall_score'].std():.4f}")

    def _log_per_doc_type(printer) -> None:
        """문서 타입별로 sub-DataFrame을 만들어 printer에 위임합니다."""
        for doc_type in _DOC_TYPES:
            sub_dt = df[df['doc_type'] == doc_type]
            if len(sub_dt) == 0:
                continue
            logger.info(f"{doc_type}:")
            printer(sub_dt, "  ")

    logger.info(f"{'#'*80}")
    logger.info(f"# 기준 모델: {ref_display}")
    logger.info(f"{'#'*80}")
    logger.info(f"총 비교된 문서 수: {df['document_id'].nunique()}")
    logger.info(f"총 비교된 문서 타입 수: {df['doc_type'].nunique()}")

    logger.info("=== 문서 타입별 통계 ===")
    for doc_type in _DOC_TYPES:
        sub = df[df['doc_type'] == doc_type]
        if len(sub) == 0:
            continue
        logger.info(f"{doc_type}:")
        for token in models:
            cnt = len(sub[sub['comparison_model'] == token])
            if cnt:
                logger.info(f"  {display_name(token)} {vs_label}: {cnt}건")

    logger.info("=== 모델별 통계 ===")
    _log_full_stats(df, "")

    logger.info("=== 문서 타입별 모델 통계 ===")
    _log_per_doc_type(_log_full_stats)

    logger.info("=== 종합 점수 비교 (lexical 20% + semantic 45% + structure 35%) ===")
    _log_overall_stats(df, "")

    logger.info("=== 문서 타입별 종합 점수 비교 ===")
    _log_per_doc_type(_log_overall_stats)


def save_results(df: pd.DataFrame, ref_token: str, timestamp: str, output_dir: str = '.') -> None:
    """기준 모델별 결과를 Excel로 저장합니다."""
    os.makedirs(output_dir, exist_ok=True)
    output_filename = os.path.join(output_dir, f'similarity_{ref_token}_as_reference_{timestamp}.xlsx')
    df.to_excel(output_filename, index=False)
    logger.info(f"결과가 저장되었습니다: {output_filename}")


# =============================================================================
# CLI 파싱
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='LLM 생성 문서 유사도 평가 스크립트',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        '--input-dir', '-i',
        default=os.environ.get('GENERATED_DOCS_DIR', '.'),
        help='마크다운 파일이 있는 디렉토리 (기본값: GENERATED_DOCS_DIR 환경변수 또는 현재 디렉토리)',
    )
    accepted_models = sorted(_ALL_MODEL_TOKENS)
    canonical_models = sorted(_CANONICAL_MODEL_TOKENS)

    parser.add_argument(
        '--reference', '-r',
        nargs='+',
        choices=accepted_models,
        default=None,
        metavar='MODEL',
        help=(
            f'기준 모델 (기본값: 파일에서 발견된 모든 모델 순차 실행). '
            f'선택 가능: {canonical_models}, alias: {sorted(_MODEL_ALIASES)}'
        ),
    )
    parser.add_argument(
        '--recursive', '-R',
        action='store_true',
        default=False,
        help='하위 디렉토리의 마크다운 파일도 재귀 탐색합니다 (ADR_Sources 같은 모델별 서브디렉토리 구조에 사용)',
    )
    parser.add_argument(
        '--log-file',
        default=None,
        help='로그 파일 경로 (지정 시 DEBUG 레벨까지 파일에 기록)',
    )
    parser.add_argument(
        '--output-dir', '-o',
        default='.',
        help='Excel 결과 파일을 저장할 디렉토리 (기본값: 현재 디렉토리)',
    )
    parser.add_argument(
        '--compare', '-c',
        nargs='+',
        choices=accepted_models,
        default=None,
        metavar='MODEL',
        help=(
            f'비교 대상 모델 (기본값: 모든 모델). '
            f'예: --compare gemma qwen ministral'
        ),
    )
    return parser.parse_args()


# =============================================================================
# main
# =============================================================================

def main() -> None:
    args = parse_args()

    # 로깅 초기화
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = args.log_file or f'similarity_run_{timestamp}.log'
    setup_logging(log_file)

    generated_docs_dir = args.input_dir
    if not os.path.isdir(generated_docs_dir):
        logger.error(f"입력 디렉토리가 존재하지 않습니다: {generated_docs_dir}")
        return

    if args.recursive:
        pattern   = os.path.join(generated_docs_dir, "**", "*.md")
        all_files = glob.glob(pattern, recursive=True)
        logger.info(f"Found {len(all_files)} files (recursive) in: {generated_docs_dir}")
    else:
        all_files = glob.glob(os.path.join(generated_docs_dir, "*.md"))
        logger.info(f"Found {len(all_files)} files in: {generated_docs_dir}")

    # document_groups[document_id][doc_type][model_token] = file_path
    document_groups: dict[str, dict[str, dict[str, str]]] = {}
    found_model_tokens: set[str] = set()
    all_valid_files: list[str] = []
    duplicate_files: list[tuple[str, str, str, str, str]] = []

    for file_path in all_files:
        filename = os.path.basename(file_path)
        document_id, model_token, doc_type = extract_document_info(filename)

        if not document_id or not model_token:
            logger.debug(f"Skipping {filename}: Could not extract document info")
            continue
        if doc_type is None:
            logger.debug(f"Skipping {filename}: No document type found")
            continue

        model_files = document_groups.setdefault(document_id, {}).setdefault(doc_type, {})
        if model_token in model_files:
            duplicate_files.append((document_id, doc_type, model_token, model_files[model_token], file_path))
            logger.warning(
                "중복 파일 스킵: document_id=%s, doc_type=%s, model=%s, kept=%s, skipped=%s",
                document_id, doc_type, display_name(model_token), model_files[model_token], file_path,
            )
            continue

        model_files[model_token] = file_path
        found_model_tokens.add(model_token)
        all_valid_files.append(file_path)

    if not document_groups:
        logger.error("처리할 파일이 없습니다. --input-dir 경로를 확인하세요.")
        return

    if duplicate_files:
        logger.warning("중복 파일 %d개가 발견되어 첫 번째 파일만 사용했습니다.", len(duplicate_files))

    # 문서 캐시 프리로드 + 전역 TF-IDF 학습
    _doc_cache.preload(all_valid_files)
    fit_global_tfidf(all_valid_files)

    # 기준 모델 목록 결정 (레지스트리 등록 순서 우선, 미등록 모델은 뒤로)
    if args.reference:
        reference_tokens = list(dict.fromkeys(normalize_model_token(t) for t in args.reference))
    else:
        registry_index = {t: i for i, t in enumerate(_MODEL_REGISTRY)}
        reference_tokens = sorted(
            found_model_tokens,
            key=lambda t: registry_index.get(t, len(registry_index)),
        )

    # 비교 대상 모델 제한
    compare_tokens = {normalize_model_token(t) for t in args.compare} if args.compare else None
    if compare_tokens:
        logger.info(f"비교 대상 모델 제한: {', '.join(display_name(t) for t in compare_tokens)}")

    logger.info(f"기준 모델 실행 순서: {' → '.join(display_name(t) for t in reference_tokens)}")

    # _METRIC_GROUPS는 점수 계산용 컬럼만 포함(이중 계산 방지). 출력·통계용으로는
    # overall_document_structure_similarity도 표시해야 하므로 별도로 추가한다.
    all_numeric_cols = [c for _, cols in _METRIC_GROUPS.values() for c in cols]
    for col in _STRUCTURE_METRIC_COLS:
        if col not in all_numeric_cols:
            all_numeric_cols.append(col)

    for ref_token in reference_tokens:
        logger.info(f"{'='*80}")
        logger.info(f"  기준 모델 [{display_name(ref_token)}] 평가 시작")
        logger.info(f"{'='*80}")

        results = run_for_reference(ref_token, document_groups, compare_tokens=compare_tokens)

        if not results:
            logger.warning(f"[{display_name(ref_token)}] 결과 없음. 파일 존재 여부를 확인하세요.")
            continue

        df = pd.DataFrame(results)
        df['overall_score'] = df.apply(compute_overall_score, axis=1)

        _print_stats(df, ref_token, all_numeric_cols)
        save_results(df, ref_token, timestamp, output_dir=args.output_dir)

    logger.info(f"모든 기준 모델 평가 완료. 타임스탬프: {timestamp}")
    logger.info(f"로그 파일: {log_file}")


if __name__ == "__main__":
    main()
