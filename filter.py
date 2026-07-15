# =============================================================
# filter.py — 제외 판별 (v2.4)
# 변경점 (첫 실행 실측 반영):
#   1) prescreen(): 본문 추출 '전에' 제목만으로 1차 스크리닝
#      → 추출 대상 2,200건 → 200건 수준, 실행시간 30분 → 3분
#   2) 관련성 판정은 제목 + 본문 앞 800자에서만 탐색
#      → 푸터·관련기사·광고 오염으로 인한 무관 기사 통과 차단
#   3) 묶음/큐레이션 기사([여전사 풍향계] 등) 제외
# 원칙: 제외는 삭제가 아니라 표시. 사유를 반드시 남긴다.
# =============================================================
import re

# 여러 소식을 묶은 큐레이션 기사 — 단일 주체가 없어 3줄 요약 불가
BUNDLE_PATTERNS = [
    r"^\[.{0,10}(브리핑|풍향계|이모저모|24시|톡톡|NOW|픽|소식|동향|종합)\]",
    r"^\[(오늘의|데일리|주간|금융|증권|보험|카드|여신)",
    r"外\s*$",
    r"\.\.\.\s*外",
    r"…\s*外",
]

# 제목에 이게 있으면 금융사 언급이 있어도 무관 (업종 무관 기사)
TITLE_NOISE = [
    # 업종 무관
    "홈쇼핑", "면세점", "게임", "교회", "목사", "안경", "복날", "여행객",
    "부동산시장", "임상", "어닝 서프라이즈", "Book Review",
    # 퀴즈·이벤트·정답 안내 (앱테크성 기사)
    "퀴즈", "정답", "앱테크", "행운적금", "감사 이벤트", "출석체크",
    "룰렛", "당첨자", "경품", "리워드 지급",
    # 스포츠 대회 후원 (삼성화재배 바둑 등)
    "바둑", "해설", "배 ", "대회", "우승", "출정식",
    # 사진·인사말 기사
    "인사말하는", "기념촬영", "포토뉴스",
]

# 제목이 이 패턴이면 제외 (정규식)
TITLE_NOISE_PATTERNS = [
    r"\d+월\s*\d+일\s*(오늘의|정답)",   # "7월 9일 오늘의 퀴즈 정답"
    r"정답\s*공개",
    r"^\[N잡",
    r"^\[.{0,6}배\s",                    # [삼성화재배 ...
]


def _hit(text: str, keywords: list) -> list:
    return [k for k in keywords if k in text]


def company_keywords(cfg: dict) -> list:
    """config의 모든 회사·브랜드명 (제목 매칭용)"""
    out = []
    for g in cfg["tier1"].values():
        for companies in g.get("companies", {}).values():
            out += companies
        out += g.get("brands_standalone", [])
        out += g.get("group_keywords", [])
    for g in cfg["tier2"].values():
        for companies in g.get("subgroups", {}).values():
            out += companies
        out += g.get("brands_standalone", [])
    for names in cfg["overseas"]["subgroups"].values():
        out += names
    return list(dict.fromkeys(out))


# 제목에 나타나는 디지털·금융서비스 신호 (검색어가 아닌 판정 전용)
EXTRA_RELEVANCE = [
    # 디지털 자산·인프라
    "스테이블코인", "블록체인", "디지털자산", "가상자산", "토큰", "정산", "실증",
    "PoC", "기술검증", "송금", "결제", "페이", "오픈뱅킹", "API",
    # 시스템·조직
    "시스템", "고도화", "구축", "거버넌스", "데이터", "클라우드", "전산",
    "이상거래", "신용평가", "심사", "자동화", "무인", "비대면",
    # 채널·UX
    "뱅킹", "MTS", "HTS", "채널", "인증", "간편", "온라인", "모바일",
    "메타버스", "슈퍼앱", "제휴", "협약", "MOU", "맞손", "선정",
]


def relevance_keywords(cfg: dict) -> list:
    """관련성 키워드 = 검색어 + 로컬 + AI + 보안 + 추가어 + 앱/서비스 브랜드명

    앱·서비스 브랜드명(SOL LINK, 하나원큐, KB Pay...)이 제목에 있으면
    그 자체로 디지털 서비스 기사이므로 관련성 키워드로 취급한다.
    classifier의 BRAND_TO_COMPANY를 재사용해 매핑을 한 곳에서 관리."""
    from classifier import BRAND_TO_COMPANY
    return list(dict.fromkeys(
        cfg["search_service_keywords"]
        + cfg["local_relevance_keywords"]
        + cfg["classification"]["ai_keywords"]
        + cfg["filters"]["security_override"]
        + EXTRA_RELEVANCE
        + list(BRAND_TO_COMPANY.keys())))


# ----------------------------------------------------------
# 1차 스크리닝 — 본문 추출 '전' 호출 (제목만 사용)
# ----------------------------------------------------------
def prescreen(article: dict, cfg: dict, companies: list, relevance: list) -> dict:
    title = article.get("title", "")
    f = cfg["filters"]

    # (1) 묶음 기사 — 단, 제목에 특정 회사명이 있으면 단일 주제일 수 있으므로 통과
    #     예: [뉴스워커_하나카드] 판다 디자인 트래블로그... → 하나카드 단일 기사
    #     제외 대상: [금융권 이모저모], [오늘의 홈쇼핑] 처럼 주체가 없는 것
    for pat in BUNDLE_PATTERNS:
        if re.search(pat, title) and not _hit(title, companies):
            article["excluded"] = 1
            article["exclude_reason"] = "묶음기사(단일 주체 없음)"
            return article

    # (2) 업종 무관 노이즈
    noise = _hit(title, TITLE_NOISE)
    if noise:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(제목 노이즈: %s)" % noise[0]
        return article
    for pat in TITLE_NOISE_PATTERNS:
        if re.search(pat, title):
            article["excluded"] = 1
            article["exclude_reason"] = "무관(퀴즈·이벤트성 제목)"
            return article

    # (3) 스포츠 — 제목에 1개만 있어도 제외
    sports = _hit(title, f["sports_exclude"])
    if sports:
        article["excluded"] = 1
        article["exclude_reason"] = "스포츠(%s)" % sports[0]
        return article

    # (4) 범죄 — 보안 오버라이드 우선
    crime = _hit(title, f["crime_exclude"])
    security = _hit(title, f["security_override"])
    if crime and not security:
        article["excluded"] = 1
        article["exclude_reason"] = "범죄(%s)" % crime[0]
        return article

    # (5) 핵심: 제목에 회사·브랜드명이 반드시 있어야 함
    comp_hits = _hit(title, companies)
    if not comp_hits:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(제목에 대상 금융사 없음)"
        return article

    # (6) 제목에 서비스·AI·관련성 키워드가 있어야 함
    rel_hits = _hit(title, relevance)
    if not rel_hits:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(제목에 디지털·AI 키워드 없음: %s)" % comp_hits[0]
        return article

    article["excluded"] = 0
    article["exclude_reason"] = None
    return article


# ----------------------------------------------------------
# 2차 필터 — 본문 확보 후 호출
# ----------------------------------------------------------
def apply_filters(article: dict, cfg: dict) -> dict:
    if article.get("excluded"):        # 1차에서 이미 제외됨
        return article

    f = cfg["filters"]
    title = article.get("title", "")
    body = article.get("body") or ""
    head = body[:800]                  # 본문 앞부분만 — 푸터·관련기사 오염 차단
    text = "%s %s" % (title, head)

    security = _hit(text, f["security_override"])

    sports = _hit(text, f["sports_exclude"])
    if len(sports) >= 2:
        article["excluded"] = 1
        article["exclude_reason"] = "스포츠(%s)" % ",".join(sports[:2])
        return article

    crime = _hit(text, f["crime_exclude"])
    if crime and not security:
        article["excluded"] = 1
        article["exclude_reason"] = "범죄(%s)" % crime[0]
        return article

    promo = _hit(text, f["promo_exclude_hint"])
    substantive = _hit(text, cfg["local_relevance_keywords"]
                       + cfg["classification"]["ai_keywords"])
    if promo and not substantive:
        article["excluded"] = 1
        article["exclude_reason"] = "홍보성(%s)" % promo[0]
        return article

    article["excluded"] = 0
    article["exclude_reason"] = None
    return article
