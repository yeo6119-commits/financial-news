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


# 조사·접미 — 같은 명사가 '공무원연금공단' / '공무원연금공단과' 로 갈리는 것 방지
#
# ※ '이'는 조사 목록에서 뺀다 (JOSA_KEEP_TRAILING_I).
#    회사명 끝음절과 충돌한다: '네이버페이' → '네이버페', '카카오페이' → '카카오페',
#    '애플페이' → '애플페'. 반면 '네이버페이와'는 조사 '와'가 먼저 잡혀 '네이버페이'로
#    남기 때문에, 같은 회사가 두 토큰으로 갈려 중복 판정의 핵심 고유명사가 증발했다.
#    (실측: 481건 중 38건 토큰 오염. 우리은행-네이버페이 연금 기사 겹침 0.29→0.43)
#    제거 시 부작용 확인: 기존 데이터에서 신규 병합 0건 / 해제 0건.
JOSA_KEEP_TRAILING_I = True      # check.sh 회귀검사 마커 — 되돌리지 말 것
_JOSA = ("으로써", "으로서", "에서는", "에게는", "으로는", "이라는", "라는",
         "에서", "에게", "으로", "이라", "까지", "부터", "보다", "처럼", "마다",
         "와의", "과의", "의", "은", "는", "가", "을", "를", "에", "로",
         "과", "와", "도", "만", "께", "요")


def _strip_josa(tok: str) -> str:
    """한국어 조사 제거 — 어간이 2자 이상 남을 때만 적용."""
    for j in _JOSA:                      # 긴 조사부터 검사
        if len(tok) - len(j) >= 2 and tok.endswith(j):
            return tok[: -len(j)]
    return tok


def title_tokens(norm_title: str) -> set:
    toks = re.findall(r"[가-힣]{2,}|[a-zA-Z]{2,}|\d+[가-힣]*", norm_title)
    toks = [_strip_josa(t) for t in toks]
    return {t for t in toks if t not in STOPWORDS and len(t) >= 2}


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


# 브리핑·게시판형 묶음기사 — 여러 회사 소식을 한데 모은 글.
#   이런 기사가 클러스터 대표가 되면, 나중에 필터·검토에서 '종합기사'로 걸릴 때
#   묶여 있던 진짜 기사들까지 통째로 사라진다(실측: 우리카드 라운지 건 3개 소실).
#   대표 자격을 낮춰서 개별 기사가 대표가 되게 한다.
_ROUNDUP_RE = re.compile(
    r"^\s*\[[^\]]*(브리핑|브리프|게시판|소식|종합|모아보기|한눈에|이모저모|위클리|"
    r"데일리|투데이|은행가|증권가|보험가|카드가|금융가|\d+시)[^\]]*\]|"
    r"(뉴스\s*브리핑|금융가\s*소식|업계\s*소식)|\s外\s*$|\s外$")


def company_token_set(title: str, comp_kw: list, cfg: dict) -> set:
    """제목에서 잡힌 회사명을 토큰으로 변환한 집합.

    회사 일치는 이미 별도 게이트 조건이므로, 겹침 점수에까지 회사명이
    들어가면 이중 계산이 된다. 실측: "KB국민은행, 블록체인 국제결제망" vs
    "KB국민은행, 공동구매정기예금 출시"의 공통 토큰이 'kb','국민은행'뿐인데
    겹침 0.40이 나와 전혀 다른 사건이 같은 사건으로 묶였다.
    """
    out = set()
    for h in company_hits(title, comp_kw):
        out |= title_tokens(normalize_title(h, cfg))
    return out


# 제목 판정에서만 무시하는 일반어.
#   금융 기사 제목에 습관적으로 붙는 말들이라, 이것만 겹쳐도 무관한 기사가
#   같은 사건으로 묶인다. 실측: "하나증권 …2030 투자자 공략" vs
#   "하나증권, 푸투증권과 외국인통합계좌 개시…해외 투자자 공략" → 공통이
#   '투자자·공략'뿐인데 겹침 0.40으로 묶였다.
#   ※ 요약 기반 판정에는 적용하지 않는다 — 거기선 이 단어들이 정상 신호다.
TITLE_GENERIC = {
    "공략", "투자자", "고객", "서비스", "출시", "도입", "추진", "계획",
    "전략", "시장", "사업", "지원", "제공", "운영", "개시", "진행",
    "실시", "시행", "개선", "성장", "혁신", "협력", "맞손", "선봬",
    "나선다", "박차", "속도", "본격화", "첫선", "공개", "발표",
}


def content_overlap(a_tok: set, b_tok: set, a_comp: set, b_comp: set,
                    min_common: int = 2) -> float:
    """회사명과 일반어를 뺀 '내용 토큰'만으로 겹침을 잰다.

    회사명을 빼는 이유: 회사 일치는 이미 별도 게이트라 이중 계산이 된다.
    일반어를 빼는 이유: 습관적 표현만 겹쳐도 무관한 기사가 묶인다.
    양쪽 다 2개 미만이거나 공통이 min_common개 미만이면 근거 부족으로 0.

    한국어 복합명사(블록체인 ⊂ 블록체인망, 결제 ⊂ 기업결제)는 정확히
    일치하지 않으면 안 세어지므로 이 방식은 '놓침'이 생긴다. 놓친 건
    요약 기반 2차 판정(dedup_by_summary)이 잡는다 — 그쪽이 훨씬 정확하다.
    """
    a = a_tok - a_comp - TITLE_GENERIC
    b = b_tok - b_comp - TITLE_GENERIC
    if len(a) < 2 or len(b) < 2:
        return 0.0
    if len(a & b) < min_common:
        return 0.0
    return token_overlap(a, b)


def _score(a: dict) -> tuple:
    press = a.get("press") or ""
    title = a.get("title") or ""
    return (
        0 if _ROUNDUP_RE.search(title) else 1,     # 묶음기사는 대표 후순위
        a.get("extract_ok", 0),
        len(a.get("body") or ""),
        any(p in press for p in TRUSTED_PRESS),
        -(0 if a.get("pub_date") is None else 0),   # 발행 순서는 정렬로 처리
    )


# ----------------------------------------------------------
# 본체
# ----------------------------------------------------------
def company_hits(title: str, comp_kw: list) -> set:
    """제목에 등장하는 회사명 집합.

    dedup은 classify보다 먼저 돌기 때문에 article["company"]가 아직 비어 있다.
    회차 간 판정에서 '같은 회사인가'를 보려면 제목에서 직접 뽑아야 한다.
    """
    t = (title or "").replace(" ", "")
    return {c for c in comp_kw if c.replace(" ", "") in t}


# 기관명 접미사 — "KB국민, JP모건..." 처럼 헤드라인에서 '은행'을 생략하는
# 경우가 흔하다. company_keywords 원본 목록(다른 필터에도 쓰임)은 건드리지
# 않고, 이 요약 기반 판정에서만 접미사를 뗀 '어간'으로도 매칭한다.
_ORG_SUFFIXES = ("은행", "증권", "카드", "손해보험", "생명", "캐피탈",
                 "저축은행", "자산운용", "금융지주", "금융그룹", "금융", "보험")


def _company_stems(title: str, comp_kw: list) -> set:
    """제목에서 회사명을 찾되, 접미사 생략형도 같은 것으로 취급해 어간을 반환.

    원본 키워드(예: 'KB증권', '토스')는 길이 상관없이 그대로 매칭 — 이미 큐레이션된
    고유명사라 안전하다. 접미사를 뗀 파생 어간은 길이 3자 미만이면 버린다.
    'KB금융' → '금융' 제거 시 'KB'(2자)만 남으면 다른 모든 KB계열과 충돌하고,
    '기업은행' → '은행' 제거 시 '기업'(2자)만 남으면 '기업결제' 같은 일반 문구와
    오매칭된다. 'KB국민은행' → '은행' 제거한 'KB국민'(4자)은 특정성이 충분해 유지.
    """
    t = (title or "").replace(" ", "")
    stems = set()
    for c in comp_kw:
        bare = c.replace(" ", "")
        if bare in t:
            stems.add(bare)          # 원본 키워드는 길이 무관 (이미 고유함)
        for suf in _ORG_SUFFIXES:
            if bare.endswith(suf) and len(bare) - len(suf) >= 3:
                stem = bare[:-len(suf)]
                if stem in t:
                    stems.add(stem)
                break
    return stems


def dedup_by_summary(articles: list[dict], cfg: dict, conn=None) -> None:
    """요약 완료 후 2차 중복 판정 — 제목만으론 못 잡는 '같은 사건, 다른 제목'을 잡는다.

    실측(2026-07-26): "KB국민, JP모건 키넥시스 활용 송금 서비스 출시" vs
    "KB국민은행, 블록체인 기반 국제결제망으로 기업결제 서비스 혁신" — 제목 토큰
    겹침 0.25(임계 0.35 미달)로 살아남았지만, 요약 겹침은 0.52로 명백히 같은 사건.
    제목이 매체마다 완전히 다른 문장으로 쓰이는 반면, Groq 요약은 개조식으로
    정규화돼 있어 같은 사건이면 핵심 사실(주체·기술명·숫자)이 그대로 겹친다.

    적용 범위를 좁게 잡는다 — 같은 날 + 같은 회사(제목에서 추출) + 요약 겹침 高만
    묶는다. 이미 검증(2026-07-24 세션)에서 회사 무관 조건으로는 15쌍 중 1쌍이
    오병합됐으나, 이번엔 시간 여유가 없어 같은 조건(같은 회사)만 우선 반영한다.
    """
    thr = cfg["dedup"].get("summary_dup_threshold", 0.5)
    try:
        import filter as _flt
        comp_kw = _flt.company_keywords(cfg)
    except Exception:
        comp_kw = []

    cands = [a for a in articles if not a.get("excluded") and a.get("summary_ok")
             and a.get("summary")]
    if len(cands) < 2:
        return

    def summ_tokens(a):
        flat = (a["summary"] or "").replace("\n", " ")
        return title_tokens(normalize_title(flat, cfg))

    for a in cands:
        a["_sum_tokens"] = summ_tokens(a)
        a["_comp_hits"] = _company_stems(a.get("title"), comp_kw)

    cands.sort(key=_score, reverse=True)
    clusters: list[list[dict]] = []
    for a in cands:
        placed = False
        for cl in clusters:
            rep = cl[0]
            if not same_day(a, rep):
                continue
            if not (a["_comp_hits"] & rep["_comp_hits"]):
                continue
            if token_overlap(a["_sum_tokens"], rep["_sum_tokens"]) >= thr:
                cl.append(a)
                placed = True
                break
        if not placed:
            clusters.append([a])

    for cl in clusters:
        if len(cl) < 2:
            continue
        rep = cl[0]
        rep.setdefault("_dup_members", [])
        for dup in cl[1:]:
            ov = token_overlap(dup["_sum_tokens"], rep["_sum_tokens"])
            dup["excluded"] = 1
            dup["exclude_reason"] = "중복(요약기준 %.2f | 대표: %s)" % (ov, rep["title"][:26])
            dup["_dup_ref"] = rep["title"]
            dup["_dup_score"] = ov
            rep["_dup_members"].append((dup["title"], dup.get("press") or "",
                                        f"요약겹침 {ov:.2f}",
                                        dup.get("naver_url") or dup.get("original_url") or ""))
            # dup이 앞 단계(제목 기준)에서 이미 자기 클러스터의 '대표'였다면,
            # 그 멤버들이 고아가 되어 화면에 별도 사건처럼 남는다.
            #   실측: 한컴위드 안면인증 기사 10건이 2개 사건으로 쪼개져 보였다
            #   (ziksir 기사가 1번 클러스터의 멤버이자 2번 클러스터의 대표).
            #   멤버를 새 대표로 옮기고 참조도 갱신한다.
            for m in dup.pop("_dup_members", []):
                rep["_dup_members"].append(m)
            dup["_dup_members"] = []

    # --- 회차 간: 과거 delivered 기사의 요약과 대조 ---
    #   제목 토큰은 한국어 복합명사 때문에 '블록체인망 vs 블록체인'을 못 잡는다.
    #   요약은 개조식으로 정규화돼 있어 같은 사건이면 핵심 사실이 그대로 겹친다.
    if conn is None:
        return
    try:
        past = dbm.find_delivered_summaries(conn, days=cfg["dedup"].get("cross_run_days", 3))
    except Exception:
        return
    if not past:
        return
    past_info = []
    for p in past:
        flat = (p["summary"] or "").replace("\n", " ")
        past_info.append((title_tokens(normalize_title(flat, cfg)),
                          _company_stems(p["title"], comp_kw),
                          p["title"], p["company"], p["pub_date"], p["url"]))
    for a in articles:
        if a.get("excluded") or not a.get("_sum_tokens"):
            continue
        for ptok, pcomp, ptitle, pcompany, pdate, purl in past_info:
            if not (a["_comp_hits"] & pcomp):
                continue
            ov = token_overlap(a["_sum_tokens"], ptok)
            if ov >= thr:
                a["excluded"] = 1
                a["exclude_reason"] = "기열람(요약 동일사건 %.2f: %s)" % (ov, ptitle[:24])
                a["_dup_ref"] = ptitle
                a["_dup_ref_company"] = pcompany
                a["_dup_ref_date"] = pdate
                a["_dup_ref_url"] = purl
                a["_dup_score"] = ov
                # 이 기사가 배치 클러스터의 대표였다면 멤버들도 함께 기열람 처리.
                #   안 그러면 대표만 사라지고 멤버들이 별도 사건처럼 남는다.
                for m in a.pop("_dup_members", []):
                    for sib in articles:
                        if sib is a or sib.get("_dup_ref") != a["title"]:
                            continue
                        sib["_dup_ref"] = ptitle
                        sib["_dup_ref_company"] = pcompany
                        sib["_dup_ref_date"] = pdate
                        sib["_dup_ref_url"] = purl
                a["_dup_members"] = []
                break


def dedup(conn, articles: list[dict], cfg: dict) -> list[dict]:
    """excluded 안 된 기사들에 대해:
    1) 과거 delivered 완전 일치 → 기열람 제외
    2) 배치 내 해시·유사도 중복 → 대표 1건 외 중복 표시
    반환: 동일 리스트 (excluded/exclude_reason/dup_of 갱신)"""
    thr = cfg["dedup"]["title_similarity_threshold"]
    # 회차 간(기열람) 완화 임계 — 같은 회사일 때만 적용
    cross_thr = cfg["dedup"].get("cross_run_threshold", 0.38)
    try:
        import filter as _flt
        comp_kw = _flt.company_keywords(cfg)
    except Exception:
        comp_kw = []

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
        hit = dbm.url_or_title_delivered(conn, a["url_hash"], a["norm_title_hash"])
        if hit:
            a["excluded"] = 1
            a["exclude_reason"] = "기열람(delivered 완전 일치)"
            a["_dup_ref"] = hit.get("title")
            a["_dup_ref_company"] = hit.get("company")
            a["_dup_ref_date"] = hit.get("pub_date")
            a["_dup_ref_url"] = hit.get("url")

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
                              title_tokens(normalize_title(p["title"], cfg)),
                              company_hits(p["title"], comp_kw),
                              p["company"], p["pub_date"], p["url"],
                              company_token_set(p["title"], comp_kw, cfg)))
        for a in articles:
            if a.get("excluded"):
                continue
            atok = a["_tokens"]
            acomp = company_hits(a.get("title"), comp_kw)
            actok = company_token_set(a.get("title"), comp_kw, cfg)
            try:
                afp = int(a["body_fingerprint"], 16) if a.get("body") else 0
            except (ValueError, TypeError):
                afp = 0
            for fp, ptitle, ptok, pcomp, pcompany, pdate, purl, pctok in past_info:
                # (i) 본문 완전 재탕
                if afp:
                    try:
                        if hamming(afp, int(fp, 16)) <= 3:
                            a["excluded"] = 1
                            a["exclude_reason"] = f"기열람(본문 재탕: {ptitle[:24]})"
                            a["_dup_ref"] = ptitle
                            a["_dup_ref_company"] = pcompany
                            a["_dup_ref_date"] = pdate
                            a["_dup_ref_url"] = purl
                            break
                    except (ValueError, TypeError):
                        pass
                # (ii) 제목 핵심 토큰 겹침 (같은 사건)
                #   실측: 회차를 넘나드는 실제 중복은 0.35~0.44에 몰려 있고
                #   0.45~0.49 구간은 비어 있다. 0.5 단일 임계로는 거의 다 샜다.
                #   회사가 같으면 완화 임계(cross_run)를 적용해 잡는다.
                #   단, 겹침은 회사명을 뺀 '내용 토큰'으로 잰다 — 회사명이
                #   게이트와 점수에 이중으로 쓰이면 무관한 기사가 묶인다.
                #
                #   회사가 둘 다 잡히는데 서로 다르면(explicit conflict) 겹침이
                #   아무리 높아도 매칭하지 않는다. 예전엔 ov>=0.5 무조건매칭이
                #   이 검사보다 먼저 통과돼, "우리은행 AX" 기사와 "모건스탠리
                #   AI 도입" 기사가 공통 토큰 'ai'·'기업' 둘만으로 묶였다.
                if acomp and pcomp and not (acomp & pcomp):
                    continue
                ov = content_overlap(atok, ptok, actok, pctok)
                same_comp = bool(acomp & pcomp)
                if ov >= 0.5 or (same_comp and ov >= cross_thr):
                    a["excluded"] = 1
                    a["exclude_reason"] = f"기열람(동일 사건 {ov:.2f}: {ptitle[:24]})"
                    a["_dup_ref"] = ptitle
                    a["_dup_ref_company"] = pcompany
                    a["_dup_ref_date"] = pdate
                    a["_dup_ref_url"] = purl
                    a["_dup_score"] = ov
                    break

    # 2) 배치 내 중복 클러스터링
    live = [a for a in articles if not a.get("excluded")]
    for a in live:
        a["_comp"] = company_hits(a.get("title"), comp_kw)
        a["_comp_tok"] = company_token_set(a.get("title"), comp_kw, cfg)
    # 언론사 차단 소스는 대표가 되지 못하게 후순위
    live.sort(key=lambda a: (any(p in (a.get("press") or "") for p in BLOCKED_PRESS), ), )
    def _matches(a, b) -> bool:
        """두 기사가 같은 사건인가.

        회사 충돌 검사를 맨 앞에 둔다. 예전엔 맨 뒤에 있어서, 그 앞의
        title_sim(문자열 유사도)이나 body_hash(본문 완전일치)가 먼저
        True를 반환하면 회사가 달라도 그냥 통과됐다.
        실측: "AI가 서류 맡고 RM은 기업 만난다...우리은행 기업여신 AX 본격화"
        vs "모건스탠리 'AI 도입 기업, 이익률 개선 뚜렷'" — 공통 내용 토큰이
        'ai'·'기업' 둘뿐인데 content_overlap 0.5(무조건 매칭 기준)를 넘겨
        전혀 다른 회사·사건이 하나로 묶였다.
        """
        ca, cb = a.get("_comp"), b.get("_comp")
        if ca and cb and not (ca & cb):
            return False
        # 본문 완전일치는 '본문이 실제로 있을 때'만 신뢰한다.
        #   추출 실패·차단 페이지·짧은 안내문이면 서로 다른 기사도 같은 본문이
        #   되어 버린다. 실측: "한화투자증권 연금상담센터 신설"과 "우리카드
        #   더라운지 서비스"가 '본문동일, 본문지문 0'으로 묶였다.
        #   지문이 0이면 본문에서 유의미한 토큰이 안 나온 것 → 신뢰 불가.
        body_ok = (a.get("body_fingerprint") not in (None, "", "0") and
                   b.get("body_fingerprint") not in (None, "", "0") and
                   len(a.get("body") or "") >= 300 and len(b.get("body") or "") >= 300)
        if a["norm_title_hash"] == b["norm_title_hash"]:
            return True
        if body_ok and a["body_hash"] and a["body_hash"] == b["body_hash"]:
            return True
        if title_sim(a["norm_title"], b["norm_title"]) >= thr:
            return True
        if (body_ok and
                hamming(int(a["body_fingerprint"], 16),
                        int(b["body_fingerprint"], 16)) <= 6):
            return True
        overlap = content_overlap(a["_tokens"], b["_tokens"],
                                  a.get("_comp_tok", set()), b.get("_comp_tok", set()))
        # 같은 날+겹침0.35, 또는 날짜 무관+겹침0.5(강한 겹침)
        return (same_day(a, b) and overlap >= 0.35) or overlap >= 0.5

    clusters: list[list[dict]] = []
    for a in live:
        placed = False
        # 묶음기사(브리핑·게시판)는 filter 단계에서 이미 제외된다.
        #   혹시 새 형태가 새어 들어와도 클러스터의 '다리'가 되지 않도록
        #   여기서도 단독 처리한다(이중 방어).
        if _ROUNDUP_RE.search(a.get("title") or ""):
            clusters.append([a])
            continue
        for cl in clusters:
            rep = cl[0]
            # 대표와 회사가 겹치지 않으면 합류 불가.
            #   전이적 연결만 두면 A-B, B-C로 이어져 A와 C가 무관한데도
            #   한 덩어리가 된다(실측: KB증권 퇴직연금 클러스터가 신한금융
            #   교육생 모집·KB손보 중대재해까지 흡수, 229건→16클러스터).
            #   대표를 기준점으로 고정해 주제 이탈을 막는다.
            if rep.get("_comp") and a.get("_comp") and not (rep["_comp"] & a["_comp"]):
                continue
            # 대표뿐 아니라 클러스터 내 '아무 멤버와든' 겹치면 합류(전이적 연결).
            #   대표하고만 비교하면 같은 사건이 '성료'류/'개최'류로 쪼개진다.
            #   (SKT·하나금융 해커톤이 2개 클러스터로 갈려 둘 다 노출된 버그)
            if any(_matches(a, m) for m in cl):
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
        rep["_dup_members"] = []
        for dup in cl[1:]:
            ov = token_overlap(dup["_tokens"], rep["_tokens"])
            ts = title_sim(dup["norm_title"], rep["norm_title"])
            # 어떤 근거로 묶였는지 기록 — 검수·튜닝에 필요
            why = []
            if dup["norm_title_hash"] == rep["norm_title_hash"]:
                why.append("제목동일")
            if dup.get("body_hash") and dup["body_hash"] == rep.get("body_hash"):
                why.append("본문동일")
            if ts >= thr:
                why.append(f"제목유사 {ts:.2f}")
            if ov >= 0.35:
                why.append(f"토큰겹침 {ov:.2f}")
            if dup.get("body") and rep.get("body"):
                try:
                    hd = hamming(int(dup["body_fingerprint"], 16),
                                 int(rep["body_fingerprint"], 16))
                    if hd <= 6:
                        why.append(f"본문지문 {hd}")
                except (ValueError, TypeError):
                    pass
            dup["excluded"] = 1
            dup["exclude_reason"] = "중복(%s | 대표: %s)" % (
                ", ".join(why) or "동일", rep["title"][:26])
            dup["dup_of_title"] = rep["title"]
            dup["_dup_ref"] = rep["title"]
            dup["_dup_score"] = ov
            rep["_dup_members"].append((dup["title"], dup.get("press") or "",
                                        ", ".join(why),
                                        dup.get("naver_url") or dup.get("original_url") or ""))

    return articles
