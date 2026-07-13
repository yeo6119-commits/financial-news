# =============================================================
# deduplicator.py — 중복 제거 (v2.3)
# 배치 내: 해시 + 유사도 / 과거 delivered: 완전 일치만 (후속 보도 보호)
# =============================================================
import hashlib
import re
from difflib import SequenceMatcher

import db as dbm


# ----------------------------------------------------------
# 제목 정규화
# ----------------------------------------------------------
def normalize_title(title: str, cfg: dict) -> str:
    t = title or ""
    for tag in cfg["title_normalize"]["remove_brackets"]:
        t = t.replace(tag, "")
    t = re.sub(r"^\s*\[[^\]]{1,12}\]", "", t)          # 남은 짧은 대괄호 태그
    t = re.sub(r"[\"'“”‘’『』「」<>《》]", "", t)      # 따옴표류
    t = re.sub(r"[^\w가-힣 ]", " ", t)                  # 특수문자 통일
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:24]


# ----------------------------------------------------------
# simhash (본문 fingerprint)
# ----------------------------------------------------------
def simhash(text: str, bits: int = 64) -> int:
    if not text:
        return 0
    tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}", text.lower())
    v = [0] * bits
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if v[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


# ----------------------------------------------------------
# 제목 핵심 토큰 (한국어 중복 판정용)
#  - 조사/접미 제거 없이 2글자 이상 명사·숫자·영문 추출
#  - "신한투자증권 정보보호 171억 투자"와
#    "신한투자증권, 정보보호에 171억 투자…AI 보안" 를 같은 사건으로 인식
# ----------------------------------------------------------
STOPWORDS = {"기자", "단독", "속보", "종합", "오늘", "밝혀", "위해",
             "관련", "대상", "지난", "이번", "회사", "기대", "목표", "총력",
             "가동", "완성", "전사적", "선제", "반영", "확대", "강화", "대응",
             "시대", "체계", "기준", "안전성", "신뢰", "모범사례", "가이드라인"}


def title_tokens(norm_title: str) -> set:
    toks = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+[가-힣]*", norm_title)
    return {t for t in toks if t not in STOPWORDS}


def token_overlap(a: set, b: set) -> float:
    """자카드 유사도 — 짧은 쪽 기준으로 보정 (제목 길이 편차 흡수)"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def same_day(a: dict, b: dict) -> bool:
    da = (a.get("pub_date") or "")[:10]
    db_ = (b.get("pub_date") or "")[:10]
    return bool(da) and da == db_


# ----------------------------------------------------------
# 대표 기사 점수 (높을수록 대표)
# ----------------------------------------------------------
TRUSTED_PRESS = ["전자신문", "머니투데이", "한국경제", "매일경제", "서울경제",
                 "연합뉴스", "조선비즈", "이데일리", "뉴스핌", "ZDNet"]
BLOCKED_PRESS = ["Fintechtoday", "핀테크투데이"]


def _score(a: dict) -> tuple:
    press = a.get("press") or ""
    return (
        a.get("extract_ok", 0),
        len(a.get("body") or ""),
        any(p in press for p in TRUSTED_PRESS),
        -(0 if a.get("pub_date") is None else 0),   # 발행 순서는 정렬로 처리
    )


# ----------------------------------------------------------
# 본체
# ----------------------------------------------------------
def dedup(conn, articles: list[dict], cfg: dict) -> list[dict]:
    """excluded 안 된 기사들에 대해:
    1) 과거 delivered 완전 일치 → 기열람 제외
    2) 배치 내 해시·유사도 중복 → 대표 1건 외 중복 표시
    반환: 동일 리스트 (excluded/exclude_reason/dup_of 갱신)"""
    thr = cfg["dedup"]["title_similarity_threshold"]

    # 정규화·해시·fingerprint 부여
    for a in articles:
        a["norm_title"] = normalize_title(a["title"], cfg)
        a["norm_title_hash"] = sha(a["norm_title"])
        a["body_hash"] = sha(a["body"]) if a.get("body") else None
        a["body_fingerprint"] = format(simhash(a.get("body") or ""), "x")
        a["_tokens"] = title_tokens(a["norm_title"])

    # 1-a) 과거 delivered 완전 일치 (URL / 정규화 제목)
    for a in articles:
        if a.get("excluded"):
            continue
        if dbm.url_or_title_delivered(conn, a["url_hash"], a["norm_title_hash"]):
            a["excluded"] = 1
            a["exclude_reason"] = "기열람(delivered 완전 일치)"

    # 1-b) 과거 delivered 재탕 제외 — 두 방식 병행
    #      (i) 본문 simhash 거리 <=3 (완전 재탕)
    #      (ii) 제목 핵심 토큰 겹침 >=0.5 (같은 사건 다른 제목)
    #           같은 보도자료를 매체가 다시 쓴 경우 본문 지문은 벌어져도
    #           제목의 회사·브랜드·핵심어는 공유됨
    past = dbm.find_delivered_for_dedup(conn, days=3)
    if past:
        past_info = []
        for p in past:
            past_info.append((p["body_fingerprint"], p["title"],
                              title_tokens(normalize_title(p["title"], cfg))))
        for a in articles:
            if a.get("excluded"):
                continue
            atok = a["_tokens"]
            try:
                afp = int(a["body_fingerprint"], 16) if a.get("body") else 0
            except (ValueError, TypeError):
                afp = 0
            for fp, ptitle, ptok in past_info:
                # (i) 본문 완전 재탕
                if afp:
                    try:
                        if hamming(afp, int(fp, 16)) <= 3:
                            a["excluded"] = 1
                            a["exclude_reason"] = f"기열람(본문 재탕: {ptitle[:24]})"
                            break
                    except (ValueError, TypeError):
                        pass
                # (ii) 제목 핵심 토큰 겹침 (같은 사건)
                if token_overlap(atok, ptok) >= 0.5:
                    a["excluded"] = 1
                    a["exclude_reason"] = f"기열람(동일 사건: {ptitle[:24]})"
                    break

    # 2) 배치 내 중복 클러스터링
    live = [a for a in articles if not a.get("excluded")]
    # 언론사 차단 소스는 대표가 되지 못하게 후순위
    live.sort(key=lambda a: (any(p in (a.get("press") or "") for p in BLOCKED_PRESS), ), )
    clusters: list[list[dict]] = []
    for a in live:
        placed = False
        for cl in clusters:
            rep = cl[0]
            same_hash = (a["norm_title_hash"] == rep["norm_title_hash"]) or \
                        (a["body_hash"] and a["body_hash"] == rep["body_hash"])
            similar_title = title_sim(a["norm_title"], rep["norm_title"]) >= thr
            similar_body = (a.get("body") and rep.get("body") and
                            hamming(int(a["body_fingerprint"], 16),
                                    int(rep["body_fingerprint"], 16)) <= 6)
            # 한국어 보완: 같은 날짜 + 제목 핵심 토큰 60% 이상 겹침 → 동일 사건
            overlap = token_overlap(a["_tokens"], rep["_tokens"])
            # 같은 사건 판정: 같은 날+겹침0.35, 또는 날짜 무관+겹침0.5(강한 겹침)
            same_event = (same_day(a, rep) and overlap >= 0.35) or overlap >= 0.5
            if same_hash or similar_title or similar_body or same_event:
                cl.append(a)
                placed = True
                break
        if not placed:
            clusters.append([a])

    for cl in clusters:
        if len(cl) < 2:
            continue
        cl.sort(key=_score, reverse=True)
        rep = cl[0]
        for dup in cl[1:]:
            dup["excluded"] = 1
            dup["exclude_reason"] = f"중복(대표: {rep['title'][:30]})"
            dup["dup_of_title"] = rep["title"]

    return articles
