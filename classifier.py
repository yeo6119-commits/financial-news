# =============================================================
# classifier.py — 금융그룹·업권·디지털/AI 분류 (v2.5)
# 변경점 (실측 반영):
#   1) 검색 키워드의 menu_id를 신뢰하지 않음 → 제목 기준 재판정
#      "하나금융 AI"로 걸린 카카오뱅크 기사가 하나 탭에 꽂히던 문제 해결
#   2) 제목에 없으면 본문 앞 500자, 그래도 없으면 검색 키워드 fallback
#   3) company(회사명)를 별도 저장 → HTML에서 회사별 소제목 렌더링
# =============================================================
from collections import Counter

# Tier2 세부 그룹을 묶는 상위 메뉴 (B안: 탭은 그룹 단위)
TIER2_MENU = {
    "지방금융": "regional",
    "국책특수": "policy",
    "비지주증권": "nonholding",
    "비지주카드보험": "nonholding",
}

# 앱·브랜드명 → 소속 회사로 정규화
# (하나원큐 기사가 '하나원큐' 소제목이 아니라 '하나은행'으로 묶이도록)
BRAND_TO_COMPANY = {
    # 하나
    "하나원큐": "하나은행", "원큐": "하나은행", "아이부자": "하나은행",
    "하나페이": "하나카드", "원큐페이": "하나카드", "트래블로그": "하나카드",
    "하나증권 MTS": "하나증권",
    # 신한
    "신한 SOL": "신한은행", "신한SOL": "신한은행", "신한 쏠": "신한은행",
    "신한쏠": "신한은행", "쏠": "신한은행", "SOL": "신한은행",
    "신한 슈퍼SOL": "신한금융", "신한슈퍼SOL": "신한금융",
    "슈퍼쏠": "신한금융", "슈퍼SOL": "신한금융",
    "SOL페이": "신한카드", "쏠페이": "신한카드",
    "SOL LINK": "신한투자증권", "쏠 링크": "신한투자증권", "솔링크": "신한투자증권",
    # KB
    "KB스타뱅킹": "KB국민은행", "스타뱅킹": "KB국민은행",
    "리브넥스트": "KB국민은행", "리브 넥스트": "KB국민은행", "리브": "KB국민은행",
    "KB Pay": "KB국민카드", "KB페이": "KB국민카드",
    "KB증권 MTS": "KB증권", "마블미니": "KB증권",
    # 우리
    "우리WON뱅킹": "우리은행", "우리WON": "우리은행", "원뱅킹": "우리은행",
    "WON": "우리은행", "위비": "우리은행", "우리페이": "우리카드",
    # NH
    "NH올원뱅크": "NH농협은행", "올원뱅크": "NH농협은행", "올원": "NH농협은행",
    "NH콕뱅크": "NH농협은행", "콕뱅크": "NH농협은행",
    "나무증권": "NH투자증권", "NAMUH": "NH투자증권", "올원페이": "NH농협카드",
    # 비지주·기타
    "모니모": "삼성금융네트웍스",
    "영웅문": "키움증권",
    "M-able": "미래에셋증권", "엠에이블": "미래에셋증권", "미래에셋 M-STOCK": "미래에셋증권",
    "mPOP": "삼성증권",
    "현대카드앱": "현대카드",
    "다이렉트원": "현대해상",
    "아이원뱅크": "IBK기업은행", "i-ONE뱅크": "IBK기업은행", "i-ONE Bank": "IBK기업은행",
    "iM뱅크앱": "iM뱅크", "썸뱅크": "iM뱅크",
    "땡겨요": "신한은행",
}


# 회사명 → 업권 추론 (Tier2/해외는 companies 구조가 없음)
SECTOR_HINTS = [
    ("은행", ["은행", "뱅크", "뱅킹"]),
    ("증권", ["증권", "투자증권"]),
    ("카드", ["카드"]),
    ("캐피탈", ["캐피탈"]),
    ("보험", ["생명", "화재", "손해보험", "손보"]),
    ("저축은행", ["저축은행"]),
]


def _sector_from_name(name: str) -> str:
    for sector, pats in SECTOR_HINTS:
        if any(p in name for p in pats):
            return sector
    return "기타"


def build_index(cfg: dict) -> list:
    """(회사명, menu_id, subgroup, sector) 목록. 긴 이름 우선 매칭."""
    idx = []
    for gname, g in cfg["tier1"].items():
        mid = g["menu_id"]
        for sector, companies in g.get("companies", {}).items():
            for c in companies:
                idx.append((c, mid, gname, sector))
        for b in g.get("brands_standalone", []):
            idx.append((b, mid, gname, _sector_from_name(b)))
        for gk in g.get("group_keywords", []):
            idx.append((gk, mid, gname, "그룹"))

    for gname, g in cfg["tier2"].items():
        mid = TIER2_MENU.get(gname, g["menu_id"])
        for sub, companies in g.get("subgroups", {}).items():
            for c in companies:
                idx.append((c, mid, sub, _sector_from_name(c)))
        for b in g.get("brands_standalone", []):
            idx.append((b, mid, gname, _sector_from_name(b)))

    ov = cfg["overseas"]
    for sub, names in ov["subgroups"].items():
        for n in names:
            idx.append((n, ov["menu_id"], sub, "해외"))

    # 긴 회사명 먼저 (예: "신한투자증권"이 "신한"보다 우선)
    idx.sort(key=lambda x: len(x[0]), reverse=True)
    return idx


def _match(text: str, idx: list) -> list:
    """텍스트에 등장하는 회사 항목. 이미 매칭된 긴 이름의 부분문자열은 제외."""
    hits, consumed = [], []
    for name, mid, sub, sector in idx:
        if name in text and not any(name in c for c in consumed):
            hits.append((name, mid, sub, sector))
            consumed.append(name)
    return hits


def classify(article: dict, cfg: dict, idx: list) -> dict:
    title = article.get("title", "")
    body = article.get("body") or ""
    head = body[:500]

    # 1순위: 제목에 등장하는 회사 (기사의 주체)
    hits = _match(title, idx)
    source = "title"

    # 2순위: 본문 앞부분
    if not hits:
        hits = _match(head, idx)
        source = "body"

    if hits:
        # 제목 앞쪽에 등장한 회사를 주체로 (보통 "A사, ~했다" 구조)
        hits.sort(key=lambda h: title.find(h[0]) if h[0] in title else 999)
        name, menu_id, subgroup, sector = hits[0]
        # 그룹 키워드만 잡혔는데 계열사도 함께 언급되면 계열사 우선
        if sector == "그룹" and len(hits) > 1:
            for h in hits[1:]:
                if h[1] == menu_id and h[3] != "그룹":
                    name, menu_id, subgroup, sector = h
                    break
        # 앱·브랜드명이면 소속 회사로 정규화 (하나원큐 → 하나은행)
        company = BRAND_TO_COMPANY.get(name, name)
        if company != name:
            sector = "그룹" if company in ("신한금융", "삼성금융네트웍스") \
                     else _sector_from_name(company)
    else:
        # 3순위: 검색 키워드 fallback (수집 시 부여된 값)
        menu_id = article.get("menu_id") or "etc"
        subgroup = article.get("subgroup") or "기타"
        sector = article.get("sector_hint") or "기타"
        company = subgroup
        source = "keyword"

    # 디지털 / AI
    text = f"{title} {head}"
    ai_hits = [k for k in cfg["classification"]["ai_keywords"] if k in text]
    article["dig_ai"] = "AI" if ai_hits else "디지털"

    # 매칭 키워드 — 회사·브랜드 + 서비스 키워드 + AI 키워드
    # 단, 동사성 일반어(출시·도입·확대 등)는 정보량이 없어 제외
    SKIP_KW = {"출시", "도입", "확대", "개선", "적용", "오픈", "선정",
               "탑재", "고도화", "개편", "리뉴얼", "협약", "MOU", "맞손"}
    matched = [h[0] for h in hits[:3]]
    for k in cfg["search_service_keywords"]:
        if k in title and k not in matched and k not in SKIP_KW:
            matched.append(k)
    matched += [k for k in ai_hits if k not in matched]

    article["fin_group"] = menu_id
    article["subgroup"] = subgroup
    article["company"] = company
    article["sector"] = sector
    article["classify_source"] = source
    article["matched_keywords"] = ", ".join(dict.fromkeys(matched))[:200]
    return article
