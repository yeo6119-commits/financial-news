# =============================================================
# foreign_store.py — 해외(영문) 기사 저장소
#
# 국내 파이프라인(news.db)과 완전히 분리된 별도 트랙이다. 하루에 파일 하나(KST 날짜)씩 쌓고
# 지우지 않는다(영구 보관). 매 실행 바뀌는 파일은 그날 것 하나뿐이라 저장소 증가가 작다.
#   foreign/data/2026-10-29.json = {"date", "articles": [...], "dropped": [...]}
# 국내 쪽은 페이지를 만들 때 load_recent()로 읽어 '해외 영문' 탭에 얹기만 한다.
# =============================================================
import json
import os
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
DATA_DIR = os.path.join("foreign", "data")


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def _path(day: str, root: str = DATA_DIR) -> str:
    return os.path.join(root, f"{day}.json")


def load_day(day: str, root: str = DATA_DIR) -> dict:
    try:
        with open(_path(day, root), encoding="utf-8") as fh:
            d = json.load(fh)
        d.setdefault("articles", [])
        d.setdefault("dropped", [])
        return d
    except (OSError, ValueError):
        return {"date": day, "articles": [], "dropped": []}


def save_day(day: str, data: dict, root: str = DATA_DIR) -> None:
    os.makedirs(root, exist_ok=True)
    data["date"] = day
    with open(_path(day, root), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def load_recent(days: int = 60, root: str = DATA_DIR) -> list:
    """최근 days일의 기사를 게재 시각 최신순으로. 각 기사에 'day'(저장한 날)를 붙인다. 실패해도 빈 목록."""
    out = []
    try:
        names = sorted(f for f in os.listdir(root) if f.endswith(".json"))
    except OSError:
        return out
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    for f in names:
        day = f[:-5]
        if day < cutoff:
            continue
        for a in load_day(day, root)["articles"]:
            a = dict(a)
            a["day"] = day
            out.append(a)
    out.sort(key=lambda a: a.get("pub_date") or "", reverse=True)
    return out


def load_days(days: int = 60, root: str = DATA_DIR) -> list:
    """최근 days일의 날짜별 묶음 [{date, articles, dropped}] (최신 날짜 먼저). 페이지 생성용. 실패해도 빈 목록."""
    try:
        names = sorted((f for f in os.listdir(root) if f.endswith(".json")), reverse=True)
    except OSError:
        return []
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = []
    for f in names:
        if f[:-5] < cutoff:
            continue
        d = load_day(f[:-5], root)
        d["articles"].sort(key=lambda a: a.get("pub_date") or "", reverse=True)
        out.append(d)
    return out
