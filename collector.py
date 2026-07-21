# =============================================================
# collector.py — 네이버 뉴스 API 수집 (v2.2)
# 핵심 원칙:
#   1) 수집 단계 무필터 — 기간 필터만 수행, 판단은 이후 단계
#   2) 페이지 전체가 기간 이전일 때만 중단 + 1페이지 추가 확인
#   3) start=1000 도달 시 절단 플래그
#   4) API 호출 수 계측
# =============================================================
import os
import time
import hashlib
import re
import html
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

KST = timezone(timedelta(hours=9))
API_URL = "https://openapi.naver.com/v1/search/news.json"


# ----------------------------------------------------------
# 검색 키워드 생성
# ----------------------------------------------------------
def build_keywords(cfg: dict) -> list[dict]:
    """config로부터 검색식 목록 생성.
    반환: [{query, menu_id, subgroup, sector_hint}] """
    kws = []
    svc = cfg["search_service_keywords"]
    svc_lite = cfg["search_service_keywords_lite"]
    grp_svc = cfg["group_service_keywords"]

    # --- Tier 1 ---
    for gname, g in cfg["tier1"].items():
        mid = g["menu_id"]
        # 브랜드 단독
        for b in g.get("brands_standalone", []):
            kws.append({"query": b, "menu_id": mid, "subgroup": gname, "sector_hint": None})
        # 회사명 × 서비스 키워드 (standalone_mode 그룹은 회사명 단독)
        for sector, companies in g.get("companies", {}).items():
            for c in companies:
                if g.get("standalone_mode"):
                    kws.append({"query": c, "menu_id": mid, "subgroup": sector, "sector_hint": None})
                else:
                    for s in svc:
                        kws.append({"query": f"{c} {s}", "menu_id": mid,
                                    "subgroup": gname, "sector_hint": sector})
        # 그룹 전략 키워드
        for gk in g.get("group_keywords", []):
            for s in grp_svc:
                kws.append({"query": f"{gk} {s}", "menu_id": mid,
                            "subgroup": gname, "sector_hint": "그룹"})

    # --- Tier 2 ---
    for gname, g in cfg["tier2"].items():
        mid = g["menu_id"]
        for sub, companies in g.get("subgroups", {}).items():
            for c in companies:
                for s in svc_lite:
                    kws.append({"query": f"{c} {s}", "menu_id": mid,
                                "subgroup": sub, "sector_hint": None})
        for b in g.get("brands_standalone", []):
            kws.append({"query": b, "menu_id": mid, "subgroup": gname, "sector_hint": None})

    # --- 해외 ---
    ov = cfg["overseas"]
    for sub, names in ov["subgroups"].items():
        for n in names:
            for s in ov["search_keywords_combined"]:
                kws.append({"query": f"{n} {s}", "menu_id": ov["menu_id"],
                            "subgroup": sub, "sector_hint": None})

    # --- 정책·규제 (회사명 무관) ---
    ps = cfg.get("policy_section")
    if ps:
        for kw in ps["search_keywords"]:
            kws.append({"query": kw, "menu_id": ps["menu_id"],
                        "subgroup": "정책·규제", "sector_hint": "policy"})

    # 동일 query 중복 제거 (첫 매핑 유지)
    seen, out = set(), []
    for k in kws:
        if k["query"] not in seen:
            seen.add(k["query"])
            out.append(k)
    return out


# ----------------------------------------------------------
# 유틸
# ----------------------------------------------------------
def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def url_hash(url: str) -> str:
    u = re.sub(r"[?#].*$", "", (url or "").strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:24]


def parse_pubdate(s: str) -> datetime | None:
    try:
        return parsedate_to_datetime(s).astimezone(KST)
    except Exception:
        return None


# ----------------------------------------------------------
# 수집 본체
# ----------------------------------------------------------
class Collector:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.headers = {
            "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
        }
        self.api_calls = 0
        self.cutoff_keywords: list[str] = []
        self._lock = threading.Lock()
        self._session = requests.Session()

    def _call(self, query: str, start: int) -> list[dict]:
        api = self.cfg["naver_api"]
        for attempt in range(3):
            r = self._session.get(
                API_URL, headers=self.headers, timeout=10,
                params={"query": query, "display": api["display"],
                        "start": start, "sort": api["sort"]},
            )
            with self._lock:
                self.api_calls += 1
            if r.status_code == 200:
                return r.json().get("items", [])
            if r.status_code == 429:            # 레이트리밋 — 백오프
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
        return []

    def collect_keyword(self, kw: dict, start_time: datetime, end_time: datetime) -> list[dict]:
        """키워드 1개 수집. 페이지 전체가 기간 이전이면 (+1페이지 확인 후) 중단."""
        api = self.cfg["naver_api"]
        display = api["display"]
        results, start = [], 1
        old_page_seen = False   # 직전 페이지가 전부 기간 이전이었는지

        while start <= api["max_start"]:
            items = self._call(kw["query"], start)
            if not items:
                break

            page_all_old = True
            for it in items:
                pd = parse_pubdate(it.get("pubDate", ""))
                if pd is None:
                    continue
                if pd > end_time:
                    page_all_old = False
                    continue
                if pd < start_time:
                    continue
                page_all_old = False
                results.append({
                    "title": strip_tags(it.get("title")),
                    "press": None,   # 본문 추출 단계에서 확정
                    "pub_date": pd.isoformat(),
                    "original_url": it.get("originallink") or "",
                    "naver_url": it.get("link") or "",
                    "url_hash": url_hash(it.get("originallink") or it.get("link")),
                    "search_keyword": kw["query"],
                    "menu_id": kw["menu_id"],
                    "subgroup": kw["subgroup"],
                    "sector_hint": kw["sector_hint"],
                })

            if page_all_old:
                if old_page_seen:            # 두 페이지 연속 전부 기간 이전 → 중단
                    break
                old_page_seen = True         # 1페이지 추가 확인
            else:
                old_page_seen = False

            start += display
            if start > api["max_start"] and not page_all_old:
                # 상한 도달 시점에도 기간 내 기사 존재 → 절단 플래그
                with self._lock:
                    self.cutoff_keywords.append(kw["query"])

        return results

    def collect_all(self, keywords: list[dict], start_time: datetime,
                    end_time: datetime, workers: int = 8) -> list[dict]:
        """키워드를 병렬 수집 (8스레드). 네이버 API 초당 제한 내에서 안전."""
        all_items, seen_urls = [], set()
        done = [0]

        def work(kw):
            try:
                return self.collect_keyword(kw, start_time, end_time)
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for batch in ex.map(work, keywords):
                done[0] += 1
                if done[0] % 200 == 0:
                    print(f"  수집 {done[0]}/{len(keywords)} 키워드")
                for item in batch:
                    if item["url_hash"] in seen_urls:
                        continue
                    seen_urls.add(item["url_hash"])
                    all_items.append(item)
        return all_items
