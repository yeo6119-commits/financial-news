# =============================================================
# similar.py — 카드별 '비슷한 기사'(같은 사건을 다룬 다른 기사) 목록
#
# 중복으로 제외된 기사는 excluded_log에 '어느 기사의 중복인지'가 사유 문자열로 남는다.
#   중복(요약기준 0.43 | 대표: <대표 제목 앞 26자>)        — 같은 회차 안에서 묶인 기사
#   기열람(동일 사건 0.60: <이전 기사 제목 앞 24자 안팎>)   — 이전 회차에 이미 반영된 기사의 재탕
#   기열람(본문 재탕: <이전 기사 제목 앞 24자>)
# 이 사유의 제목 앞부분으로 대표 카드를 찾아 연결한다. DB 스키마는 바꾸지 않는다(렌더링 시점 계산).
#
# 한계: excluded_log 보관기간(excluded_retention_days, 기본 14일)이 지나면 목록이 사라진다.
# =============================================================
import re
from collections import defaultdict
from datetime import datetime

import outlets

# 사유 끝의 대표 제목 조각 — 제목 안에 ')'가 있어도 마지막 ')' 직전까지 취한다
_REF = re.compile(r"(?:대표: |동일 사건 [0-9.]+: |본문 재탕: )(.+)\)\s*$")
_WS = re.compile(r"\s+")

MIN_PREFIX = 10      # 이보다 짧은 조각은 다른 기사와 헷갈릴 수 있어 연결하지 않는다
MAX_PER_CARD = 20
DATE_WINDOW_DAYS = 6

def _norm(s) -> str:
    return _WS.sub("", s or "")


def outlet_name(url, press, omap) -> str:
    """언론사 이름: press → outlets.json 매핑 → 도메인 → '네이버뉴스'."""
    name = outlets.name_for(url, press, omap)
    if name:
        return name
    k = outlets.key_of(url)
    if k and k.startswith("dom:"):
        return k[4:]
    return "네이버뉴스"


def _ref_prefix(reason):
    m = _REF.search(reason or "")
    if not m:
        return None
    p = m.group(1).strip()
    return p if len(_norm(p)) >= MIN_PREFIX else None


def _day(s):
    try:
        return datetime.fromisoformat((s or "")[:19])
    except ValueError:
        return None


def build(conn, rows, omap=None) -> dict:
    """{article_id: [(언론사, 제목, 링크, 'MM-DD HH:MM'), ...]} — 최신순, 카드당 MAX_PER_CARD건.
    omap: outlets.json 매핑(없으면 파일에서 읽는다)."""
    if omap is None:
        omap = outlets.load()
    by_head = defaultdict(list)
    for a in rows:
        by_head[_norm(a["title"])[:8]].append(a)

    members = conn.execute(
        """SELECT run_id, title, url, press, reason, pub_date FROM excluded_log
           WHERE reason LIKE '중복(%대표: %' OR reason LIKE '기열람(동일 사건%'
              OR reason LIKE '기열람(본문 재탕:%'""").fetchall()

    out = defaultdict(dict)       # id -> {정규화 제목: item}
    for m in members:
        pref = _ref_prefix(m["reason"])
        if not pref:
            continue
        pn = _norm(pref)
        same_run = m["reason"].startswith("중복")
        md = _day(m["pub_date"])
        cands = []
        for a in by_head.get(pn[:8], []):
            if not _norm(a["title"]).startswith(pn):
                continue
            if same_run and a["run_id"] != m["run_id"]:
                continue                      # 같은 회차 안에서 묶인 기사만
            if not same_run and a["run_id"] >= m["run_id"]:
                continue                      # 재탕은 더 이른 회차의 카드에 붙인다
            ad = _day(a["pub_date"])
            if md and ad and abs((md - ad).days) > DATE_WINDOW_DAYS:
                continue
            cands.append(a)
        if not cands:
            continue
        card = max(cands, key=lambda a: a["run_id"])    # 재탕이면 가장 최근에 반영된 카드
        title = (m["title"] or "").strip()
        if not title or _norm(title) == _norm(card["title"]):
            continue
        link = m["url"] or ""
        if link and link in ((card["naver_url"] or ""), (card["original_url"] or "")):
            continue
        d = md.strftime("%m-%d %H:%M") if md else ""
        out[card["id"]].setdefault(_norm(title), (
            outlet_name(link, m["press"], omap), title, link, d, md or datetime.min))

    res = {}
    for aid, items in out.items():
        lst = sorted(items.values(), key=lambda x: x[4], reverse=True)[:MAX_PER_CARD]
        res[aid] = [(p, t, u, d) for p, t, u, d, _ in lst]
    return res
