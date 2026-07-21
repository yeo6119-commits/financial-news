# =============================================================
# press_collector.py — 9개 금융그룹 보도자료 수집 (v2.3)
# 원칙: 어댑터 단위 실패 허용 + 실행 통계에 실패 가시화
# URL·파라미터는 2026-05~06 확인값 — 첫 실행에서 셀렉터 재검증 필요
# =============================================================
import re
import ssl
import time
import hashlib
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def _hash(u: str) -> str:
    return hashlib.sha256(re.sub(r"[?#].*$", "", u.strip()).encode()).hexdigest()[:24]


def _parse_date(s: str) -> datetime | None:
    s = re.sub(r"[^\d]", "", s or "")
    for fmt, ln in (("%Y%m%d", 8), ("%Y%m%d%H%M", 12)):
        if len(s) >= ln:
            try:
                return datetime.strptime(s[:ln], fmt).replace(tzinfo=KST)
            except ValueError:
                pass
    return None


# 우리금융 legacy SSL 대응 어댑터
class LegacySSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.options |= 0x4          # OP_LEGACY_SERVER_CONNECT
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _mk(item_title, date, url, group, company=None):
    return {
        "title": item_title.strip(),
        "press": f"{group} 보도자료",
        "pub_date": date.isoformat() if date else None,
        "original_url": url,
        "naver_url": "",
        "url_hash": _hash(url),
        "search_keyword": f"[PR] {group}",
        "source": "press",
        "pr_company": company,
    }


# ----------------------------------------------------------
# 어댑터들 — 각각 (start_time 이후 항목 리스트) 반환
# ----------------------------------------------------------
def hana(start_time):
    out, page = [], 1
    while page <= 5:
        r = requests.post(
            "https://www.hanafn.com/ajax/mediaRoom/mediaRoom/moreList.do",
            data={"pageNo": page, "hmvpSn": "", "hnewsSn": "", "searchKey": "",
                  "searchVal": "", "searchType": "", "kwrdNm": ""},
            headers={**UA, "X-Requested-With": "XMLHttpRequest",
                     "Referer": "https://www.hanafn.com/mediaRoom/mediaRoom.do"},
            timeout=(3, 7))
        soup = BeautifulSoup(r.text, "lxml")
        items = soup.select("li")
        if not items:
            break
        stale = True
        for li in items:
            onclick = li.select_one("[onclick*='viewPage']")
            m = re.search(r"viewPage\(this,\s*(\d+)", onclick["onclick"]) if onclick else None
            if not m:
                continue
            sn = m.group(1)
            title = li.get_text(" ", strip=True)[:120]
            date = _parse_date(li.select_one(".date").get_text() if li.select_one(".date") else "")
            tag = li.select_one("[class*=tag], .hashtag")
            company = tag.get_text(strip=True).lstrip("#") if tag else None
            if date and date < start_time:
                continue
            stale = False
            url = f"https://www.hanafn.com/mediaRoom/hanaNews/newsList/view.do?hnewsSn={sn}"
            out.append(_mk(title, date, url, "하나금융", company))
        if stale:
            break
        page += 1
        time.sleep(0.3)
    return out


def kb(start_time):
    out, page = [], 1
    while page <= 10:
        r = requests.get("https://www.kbfg.com/api/kbfg/notics",
                         params={"bulbdId": 8, "pageIndex": page}, headers=UA, timeout=(3, 7))
        data = r.json()
        rows = data.get("list") or data.get("notics") or []
        if not rows:
            break
        stale = True
        for it in rows:
            date = _parse_date(str(it.get("rgcrYms") or it.get("regDt") or ""))
            if date and date < start_time:
                continue
            stale = False
            bid = it.get("bltcId") or it.get("id")
            url = f"https://www.kbfg.com/kor/pr/press/view.htm?bltcId={bid}"
            out.append(_mk(it.get("titl") or it.get("title", ""), date, url, "KB금융"))
        if stale:
            break
        page += 1
        time.sleep(0.3)
    return out


def shinhan(start_time):
    # 2026-07 확인: GET 405 → POST 시도, 실패 시 어댑터 실패 처리(헬스체크에 표시)
    r = requests.post("https://www.shinhangroup.com/api/v1/pr/report/list",
                      json={"pageType": "REPORT", "lang": "KOR", "page": 1},
                      headers={**UA, "Referer": "https://www.shinhangroup.com/kr/pr/press"},
                      timeout=(3, 7))
    r.raise_for_status()
    out = []
    for it in (r.json().get("data") or {}).get("list", []):
        date = _parse_date(str(it.get("regDate") or ""))
        if date and date < start_time:
            continue
        url = f"https://www.shinhangroup.com/kr/pr/press/{it.get('seq', '')}"
        out.append(_mk(it.get("title", ""), date, url, "신한금융"))
    return out


def woori(start_time):
    s = requests.Session()
    s.mount("https://", LegacySSLAdapter())
    r = s.get("https://www.woorifg.com/kor/pr/news/list.do", headers=UA, timeout=(3, 7))
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for row in soup.select("tr, li"):
        a = row.select_one("a[href*='view.do'], a[onclick*='view']")
        if not a:
            continue
        m = re.search(r"seq=(\d+)|view\((\d+)", a.get("href", "") + (a.get("onclick") or ""))
        if not m:
            continue
        seq = m.group(1) or m.group(2)
        date = _parse_date(row.get_text())
        if date and date < start_time:
            continue
        url = f"https://www.woorifg.com/kor/pr/news/view.do?seq={seq}"
        out.append(_mk(a.get_text(strip=True), date, url, "우리금융"))
    return out


def nh(start_time):
    r = requests.get("https://www.nhfngroup.com/user/boardList.do",
                     params={"siteId": "nhfngroup", "boardId": "4998475"},
                     headers=UA, timeout=(3, 7))
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for row in soup.select("tbody tr"):
        a = row.select_one("a")
        if not a:
            continue
        date = _parse_date(row.get_text())
        if date and date < start_time:
            continue
        href = a.get("href", "")
        url = href if href.startswith("http") else f"https://www.nhfngroup.com{href}"
        out.append(_mk(a.get_text(strip=True), date, url, "NH농협금융"))
    return out


def bnk(start_time):
    out, page = [], 1
    while page <= 3:
        r = requests.get(f"https://www.bnkfg.com/02/03.jsp?dataPageNo={page}&dataWhere=",
                         headers=UA, timeout=(3, 7))
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("tbody tr")
        if not rows:
            break
        stale = True
        for row in rows:
            a = row.select_one("a")
            if not a:
                continue
            m = re.search(r"dataSeqNo=(\d+)", a.get("href", ""))
            date = _parse_date(row.get_text())
            if date and date < start_time:
                continue
            stale = False
            title = a.get_text(strip=True)
            company = title.split("_")[0] if "_" in title[:15] else None
            url = f"https://www.bnkfg.com/02/03.jsp?dataSeqNo={m.group(1)}&dataPageNo=1&dataWhere=" if m else ""
            out.append(_mk(title, date, url, "BNK금융", company))
        if stale:
            break
        page += 1
        time.sleep(0.3)
    return out


def jb(start_time):
    out, page = [], 1
    while page <= 3:
        r = requests.get(f"https://www.jbfg.com/ko/prcenter/press.do?pageNum={page}",
                         headers=UA, timeout=(3, 7))
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("tbody tr, .board-list li")
        if not rows:
            break
        stale = True
        for row in rows:
            a = row.select_one("a")
            if not a:
                continue
            m = re.search(r"detail/(\d+)", a.get("href", ""))
            date = _parse_date(row.get_text())
            if date and date < start_time:
                continue
            stale = False
            title = a.get_text(strip=True)
            company = title.split(",")[0] if "," in title[:15] else None
            url = f"https://www.jbfg.com/ko/prcenter/press/detail/{m.group(1)}.do" if m else ""
            out.append(_mk(title, date, url, "JB금융", company))
        if stale:
            break
        page += 1
        time.sleep(0.3)
    return out


def meritz(start_time):
    # (connect, read) 튜플로 강제 — 응답이 느려도 최대 8초 안에 예외 발생.
    #   단일 정수 timeout은 read마다 리셋돼 무한정 매달릴 수 있다.
    r = requests.post("https://www.meritzgroup.com/web/pr_search.do",
                      data={"bd_div_cd": "PR001", "currentPage": 1},
                      headers=UA, timeout=(3, 5), verify=False)
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for row in soup.select("tbody tr, li"):
        a = row.select_one("a")
        if not a:
            continue
        m = re.search(r"bd_div_seq=(\d+)", a.get("href", "") + (a.get("onclick") or ""))
        date = _parse_date(row.get_text())
        if date and date < start_time:
            continue
        url = f"https://www.meritzgroup.com/web/ko/pr/pr2View.do?bd_div_cd=PR001&bd_div_seq={m.group(1)}" if m else ""
        out.append(_mk(a.get_text(strip=True), date, url, "메리츠금융"))
    return out


def im(start_time):
    r = requests.post("https://www.imfngroup.com/nbbsR1.fg", data={}, headers=UA, timeout=(3, 10))
    data = r.json() if "json" in r.headers.get("content-type", "") else {}
    rows = data.get("list") or data.get("resultList") or []
    out = []
    for it in rows:
        date = _parse_date(str(it.get("RGDT") or ""))
        if date and date < start_time:
            continue
        seq = it.get("PUTUP_WRIT_SEQ") or it.get("putup_writ_seq") or ""
        url = f"https://www.imfngroup.com/ir0105.fg?putup_writ_seq={seq}"
        item = _mk(it.get("PUTUP_WRIT_SJ") or it.get("title", ""), date, url, "iM금융")
        item["body"] = re.sub(r"<[^>]+>", " ", it.get("PUTUP_WRIT_CN") or "")[:6000]  # 본문 동봉
        out.append(item)
    return out


# 안정적인 3개 그룹만 보도자료 크롤링.
#   나머지(우리·NH·BNK·JB·메리츠·iM)는 사이트가 느리거나 불안정해 제외.
#   빠진 그룹의 기사는 네이버 뉴스 수집이 대개 커버한다.
ADAPTERS = {
    "hana": ("하나금융", "hana", hana),
    "kb": ("KB금융", "kb", kb),
    "shinhan": ("신한금융", "shinhan", shinhan),
}


def collect_press(start_time) -> tuple[list[dict], dict]:
    """모든 어댑터를 병렬 실행. (기사 리스트, {어댑터: 'ok'|에러메시지}) 반환.

    한 사이트가 느려도 전체를 막지 않도록 병렬 처리 + 어댑터별 시간 상한(25초).
    보도자료는 보조 소스이므로, 느린 사이트는 건너뛰고 나머지를 진행한다.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTimeout

    items, health = [], {}
    ADAPTER_TIMEOUT = 25          # 어댑터 하나가 25초 넘으면 포기

    def run_one(key, gname, menu_id, fn):
        got = fn(start_time)
        for g in got:
            g["menu_id"] = menu_id
            g["subgroup"] = g.get("pr_company") or gname
            g["sector_hint"] = None
        return got

    ex = ThreadPoolExecutor(max_workers=len(ADAPTERS))
    futs = {ex.submit(run_one, k, g, m, fn): k
            for k, (g, m, fn) in ADAPTERS.items()}
    try:
        for fut in as_completed(futs, timeout=ADAPTER_TIMEOUT):
            key = futs[fut]
            try:
                got = fut.result(timeout=1)
                items += got
                health[key] = f"ok ({len(got)}건)"
            except Exception as e:
                health[key] = f"실패: {str(e)[:50]}"
    except FTimeout:
        pass          # 전체 상한 도달 — 미완료 어댑터는 아래에서 표시
    # 남은(매달린) 스레드는 기다리지 않고 진행. 개별 요청에 튜플 타임아웃이
    #   걸려 있어 스레드는 곧 스스로 종료된다.
    ex.shutdown(wait=False)
    for key in ADAPTERS:
        health.setdefault(key, "실패: 응답 없음(건너뜀)")
    return items, health
