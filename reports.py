# =============================================================
# reports.py — AI·디지털 보고서·정책 발표 수집 트랙
#
# 국내 뉴스(main.py·news.db)·해외 영문 뉴스(foreign.py)와 완전히 분리된 세 번째 트랙이다.
#   수집  기관 사이트가 공개한 목록(RSS·사이트맵·게시판 목록·JSON)만 읽는다. 봇 차단(403 등)을 우회하지 않는다 —
#         막히면 그 기관은 실패로 표시하고 검색(Bing News RSS)으로 보도 소식만 대신 잡는다.
#   선별  제목에 AI·디지털 핵심어가 있어야 한다(보안·개인정보·결제·데이터 같은 주변어만으로는 통과하지 못한다).
#   요약  하지 않는다 — 기관이 공개한 설명(없으면 제목)을 그대로 쓴다. Groq를 쓰지 않는다.
#   번역  해외(영문) 항목만 제목·설명을 구독 Claude로 한국어 번역한다(reports_translate.py). 원문은 그대로 두고 화면에 원제를 같이 보인다.
#   저장  reports/data/reports.json (누적, 지우지 않음) → output/reports.html
# 어떤 항목도 조용히 사라지지 않는다 — 걸러진 후보는 사유와 함께 dropped에 남기고 페이지 맨 아래에 보여 준다.
#
# 사용: python reports.py [--only id,id] [--data-dir DIR] [--out FILE] [--lookback N]
# =============================================================
import argparse
import hashlib
import html as H
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"}
DATA_DIR = os.path.join("reports", "data")
STORE_NAME = "reports.json"


class FetchError(Exception):
    """수집원 하나가 실패한 이유 — 페이지 아래 '수집원 상태'에 그대로 보인다."""


# ---------------------------------------------------------------- 공통 도구
def _get(url: str, params=None, timeout: int = 25, tries: int = 2, headers=None, method: str = "GET", json_body=None):
    """403·404·410은 다시 해도 같으므로 바로 포기한다(차단을 우회하지 않는다)."""
    last = "접속 실패"
    for attempt in range(tries):
        try:
            if method == "POST":
                r = requests.post(url, json=json_body, headers=headers or UA, timeout=timeout)
            else:
                r = requests.get(url, params=params, headers=headers or UA, timeout=timeout)
            if r.status_code == 200:
                if "charset=" not in r.headers.get("content-type", "").lower():
                    r.encoding = r.apparent_encoding or r.encoding
                return r
            last = "HTTP %d" % r.status_code
            if r.status_code in (403, 404, 410):
                break
        except requests.RequestException as e:
            last = type(e).__name__
        if attempt < tries - 1:
            time.sleep(1.2)
    raise FetchError(last)


def _soup(r) -> BeautifulSoup:
    return BeautifulSoup(r.text, "lxml")


def _txt(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ")).strip() if el is not None else ""


def _plain(s: str, n: int = 300) -> str:
    """HTML 조각 → 평문(설명용)."""
    s = H.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s.replace("﻿", "")).strip()[:n]


_D = re.compile(r"(20\d\d)\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})")


def parse_date(s: str) -> str:
    """여러 날짜 모양 → 'YYYY-MM-DD'(KST). 못 읽으면 ''."""
    s = (s or "").strip()
    if not s:
        return ""
    if re.match(r"\d{4}-\d\d-\d\dT", s):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(KST)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    if re.match(r"[A-Za-z]{3},", s):
        try:
            dt = parsedate_to_datetime(s)
            if dt.tzinfo:
                dt = dt.astimezone(KST)
            return dt.strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            pass
    m = _D.search(s)
    return "%s-%02d-%02d" % (m[1], int(m[2]), int(m[3])) if m else ""


def _item(src: dict, title: str, url: str, date: str = "", desc: str = "", sub: str = "") -> dict:
    return {"src": src["id"], "org": src["org"], "region": src.get("region", "국내"),
            "title": re.sub(r"\s+", " ", H.unescape(title or "")).replace("﻿", "").strip(),
            "url": (url or "").split("#")[0], "date": date, "desc": desc, "sub": sub}


# ---------------------------------------------------------------- 수집원 어댑터
def fetch_fsec(src: dict, ctx: dict) -> list:
    """금융보안원 — 자료마당 게시판은 /bbs/list(JSON)로 목록을 준다. 본문 설명(contents)도 같이 온다."""
    out = []
    for menu, name in src["boards"].items():
        for page in range(1, 4):
            body = {"menuNo": str(menu), "pagingSearchDto": {"page": page, "pageSize": 20, "searchContents": "", "searchType": ""}}
            r = _get("https://www.fsec.or.kr/bbs/list", method="POST", json_body=body,
                     headers={**UA, "Content-Type": "application/json; charset=UTF-8"})
            try:
                rows = r.json().get("resultData") or []
            except ValueError:
                raise FetchError("JSON 아님")
            if not isinstance(rows, list):
                break
            for x in rows:
                d = parse_date(x.get("regDate", ""))
                out.append(_item(src, x.get("title", ""), "https://www.fsec.or.kr/bbs/detail?menuNo=%s&bbsNo=%s" % (menu, x.get("bbsNo")),
                                 d, _plain(x.get("contents", "")), name))
            if len(rows) < 20 or (rows and parse_date(rows[-1].get("regDate", "")) < ctx["cutoff"]):
                break
    return out


def fetch_fsc(src: dict, ctx: dict) -> list:
    """금융위원회 보도자료 — 서버가 그려 주는 목록(15건/쪽). 기간 밖 날짜가 나오면 멈춘다."""
    out = []
    for page in range(1, 60):
        r = _get("https://www.fsc.go.kr/no010101", params={"curPage": page})
        s = _soup(r)
        rows = 0
        last = ""
        urls = []
        for li in s.select("li"):
            a = li.select_one("a[href*='/no010101/']")
            if not a:
                continue
            t = _txt(li)
            d = parse_date(t)
            if not d:
                continue
            rows += 1
            last = d
            dept = re.search(r"담당부서\s*:\s*(.+?)\s*조회수", t)
            out.append(_item(src, _txt(a), urljoin("https://www.fsc.go.kr", a["href"].split("?")[0]), d,
                             "", "보도자료" + ((" · 담당 " + dept.group(1)) if dept else "")))
            urls.append(out[-1]["url"])
        if not rows or last < ctx["cutoff"] or all(u in ctx["known"] for u in urls):
            break
        time.sleep(0.3)
    return out


def fetch_fss(src: dict, ctx: dict) -> list:
    """금융감독원 보도자료 — 표 형태 목록."""
    out = []
    for page in range(1, 60):
        r = _get("https://www.fss.or.kr/fss/bbs/B0000188/list.do", params={"menuNo": "200218", "pageIndex": page})
        s = _soup(r)
        rows = 0
        last = ""
        urls = []
        for tr in s.select("tbody tr"):
            a = tr.select_one("a[href*='view.do']")
            d = parse_date(_txt(tr))
            if not a or not d:
                continue
            rows += 1
            last = d
            tds = [_txt(td) for td in tr.select("td")]
            dept = next((x for x in tds if x and not re.match(r"^[\d-]+$", x) and x != _txt(a) and "첨부" not in x and "다운로드" not in x), "")
            out.append(_item(src, _txt(a), urljoin(r.url, a["href"].split("&pageIndex")[0]), d,
                             "", "보도자료" + ((" · 담당 " + dept) if dept else "")))
            urls.append(out[-1]["url"])
        if not rows or last < ctx["cutoff"] or all(u in ctx["known"] for u in urls):
            break
        time.sleep(0.3)
    return out


def _meta(s: BeautifulSoup, *names) -> str:
    for n in names:
        el = s.select_one('meta[property="%s"], meta[name="%s"]' % (n, n))
        if el and el.get("content"):
            return el["content"].strip()
    return ""


def fetch_sitemap(src: dict, ctx: dict) -> list:
    """사이트맵(주소+수정일) → 새 주소만 상세 페이지의 제목·설명을 읽는다. 삼정KPMG처럼 목록 페이지가 스크립트로 그려지는 곳용."""
    r = _get(src["url"], timeout=40)
    ents = re.findall(r"<url>(.*?)</url>", r.text, re.S)
    pat = re.compile(src["match"])
    cand = []
    for e in ents:
        loc = re.search(r"<loc>([^<]+)", e)
        if not loc or not pat.search(loc.group(1)):
            continue
        d = parse_date((re.search(r"<lastmod>([^<]+)", e) or [0, ""])[1])
        if d and d >= ctx["cutoff"]:
            cand.append((d, loc.group(1).strip()))
    out, miss = [], 0
    for d, u in sorted(cand, reverse=True):
        if u in ctx["known"]:
            out.append(_item(src, "", u, d))          # 이미 본 주소 — 상세는 다시 읽지 않는다(저장된 제목을 쓴다)
            continue
        try:
            s = _soup(_get(u, tries=1, timeout=20))
        except FetchError:
            miss += 1
            continue
        title = _meta(s, "og:title") or (s.title.string if s.title else "")
        out.append(_item(src, title, u, d, _meta(s, "og:description", "description")))
        time.sleep(0.2)
    if miss:
        print("  · %s: 상세 %d건 읽지 못함" % (src["id"], miss))
    return out


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_rss(src: dict, ctx: dict) -> list:
    """RSS 1.0/2.0·Atom 공통. urls: {주소: 게시판 이름}이면 여러 피드를 차례로 읽는다(한 곳이 막혀도 나머지는 받는다)."""
    feeds = src.get("urls") or {src["url"]: src.get("sub", "")}
    out, errs = [], []
    for url, sub in feeds.items():
        try:
            out += _read_feed(src, url, sub)
        except FetchError as e:
            errs.append("%s: %s" % (sub or url[-30:], e))
        time.sleep(0.2)
    if errs and not out:
        raise FetchError("; ".join(errs)[:160])
    if errs:
        print("  · %s: 일부 피드 실패 %s" % (src["id"], "; ".join(errs)[:200]))
    return out


def _read_feed(src: dict, url: str, sub: str) -> list:
    r = _get(url)
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        raise FetchError("RSS 아님")
    out = []
    for it in root.iter():
        if _local(it.tag) not in ("item", "entry"):
            continue
        f = {}
        for ch in it:
            k = _local(ch.tag)
            if k == "link" and not (ch.text or "").strip():
                f.setdefault("link", ch.get("href", ""))
            else:
                f.setdefault(k, (ch.text or "").strip())
        date = parse_date(f.get("pubDate") or f.get("date") or f.get("published") or f.get("updated") or "")
        out.append(_item(src, f.get("title", ""), f.get("link", ""), date,
                         _plain(f.get("description") or f.get("summary") or f.get("encoded") or ""), sub))
    return out


def fetch_kcmi(src: dict, ctx: dict) -> list:
    """자본시장연구원 — 유형별 목록의 최신 4건씩(주소는 보고서 번호로 만든다)."""
    out, seen = [], set()
    for code in src["types"]:
        r = _get("https://www.kcmi.re.kr/report/report_list", params={"s_report_type": code})
        for div in _soup(r).select("div.list[id^=rsidx_]"):
            no = div["id"].replace("rsidx_", "")
            if no in seen:
                continue
            seen.add(no)
            title = _txt(div.select_one(".rpt_title strong"))
            em = div.select_one(".rpt_title em span")
            tags = " ".join(_txt(a) for a in div.select(".init_tag a"))
            out.append(_item(src, title, "https://www.kcmi.re.kr/report/report_view?report_no=" + no,
                             parse_date(_txt(em)), (_txt(div.select_one("p.txt")) + " " + tags).strip()[:300], src["types"][code]))
        time.sleep(0.3)
    return out


def fetch_kisa(src: dict, ctx: dict) -> list:
    """KISA 지식플랫폼 게시판(표 목록)."""
    out = []
    for board, name in src["boards"].items():
        r = _get("https://www.kisa.or.kr/%s" % board)
        for tr in _soup(r).select("table tbody tr"):
            a = tr.select_one("a[href*='postSeq=']")
            d = parse_date(_txt(tr))
            if not a or not d:
                continue
            seq = parse_qs(urlparse(a["href"]).query).get("postSeq", [""])[0]
            out.append(_item(src, _txt(a), "https://www.kisa.or.kr/%s/form?postSeq=%s" % (board, seq), d, "", name))
        time.sleep(0.3)
    return out


def fetch_table(src: dict, ctx: dict) -> list:
    """서버가 그려 주는 표 형태 게시판 공통(개인정보위·KB경영연구소 등). 설정: url, params, page_param, pages, row, link, sub."""
    out = []
    for page in range(1, src.get("pages", 2) + 1):
        params = dict(src.get("params", {}))
        if src.get("page_param"):
            params[src["page_param"]] = page
        r = _get(src["url"], params=params)
        rows, last = 0, ""
        for tr in _soup(r).select(src.get("row", "table tbody tr")):
            a = tr.select_one(src.get("link", "a[href]"))
            d = parse_date(_txt(tr))
            if not a or not d or not a.get("href") or a["href"].startswith(("javascript", "#")):
                continue
            rows += 1
            last = d
            out.append(_item(src, re.sub(r"\s+N$", "", _txt(a)), urljoin(r.url, a["href"]), d, "", src.get("sub", "")))   # 끝의 'N'은 새 글 표시
        if not rows or last < ctx["cutoff"]:
            break
        time.sleep(0.3)
    return out


def fetch_nia(src: dict, ctx: dict) -> list:
    """한국지능정보사회진흥원 간행물 — 목록 항목의 doBbsFView(게시판, 글번호) 호출에서 주소를 만든다."""
    out = []
    for cb, name in src["boards"].items():
        r = _get("https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do", params={"cbIdx": cb})
        for li in _soup(r).select("li"):
            a = li.select_one("a[onclick*=doBbsFView]")
            m = re.search(r"doBbsFView\('(\d+)','(\d+)'", (a.get("onclick") if a else "") or "")
            subj = li.select_one(".subject")
            d = parse_date(_txt(li.select_one(".src em")))
            if not m or not subj or not d:
                continue
            out.append(_item(src, _txt(subj), "https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?cbIdx=%s&bcIdx=%s" % (m[1], m[2]),
                             d, "", name))
        time.sleep(0.3)
    return out


def _js_unescape(s: str) -> str:
    """자바스크립트 unescape('%uAC00') 흉내 — 과기정통부 목록의 제목이 이 함수 안에 들어 있다."""
    s = re.sub(r"%u([0-9A-Fa-f]{4})", lambda m: chr(int(m[1], 16)), s)
    return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)), s).replace("\\'", "'")


def fetch_msit(src: dict, ctx: dict) -> list:
    """과학기술정보통신부 보도자료 — 목록 틀(글번호)은 HTML에 있고 제목·날짜는 같은 쪽 안의 스크립트에 들어 있다."""
    out = []
    base = "https://www.msit.go.kr/bbs/list.do"
    for page in range(1, 80):
        r = _get(base, params={"sCode": "user", "mPid": "208", "mId": "307", "pageIndex": page})
        t = r.text
        rows = {}                                           # 행 번호 → 글번호 (행 단위 toggle 블록에서 짝지어 읽는다)
        for blk in t.split('<div class="toggle">')[1:]:
            m = re.search(r"fn_detail\((\d+)\)", blk)
            k = re.search(r'id="td_NTT_SJ_(\d+)"', blk)
            if m and k:
                rows[int(k[1])] = m[1]
        titles = {int(i): _js_unescape(x) for x, i in
                  re.findall(r"unescape\('((?:[^'\\]|\\.)*)'\);\s*sHtml\+= newHtml;.*?\$\('#td_'\+'NTT_SJ'\+'_(\d+)'\)", t, re.S)}
        dates = {int(i): x for i, x in re.findall(r"^\s*\$\('#td_'\+'REG_DT'\+'_(\d+)'\)\.html\('([^']*)'\)", t, re.M)}
        got, last, urls = 0, "", []
        for i, no in sorted(rows.items()):
            d = parse_date(dates.get(i, ""))
            title = titles.get(i, "")
            if not d or not title:
                continue
            got += 1
            last = d
            out.append(_item(src, title, "https://www.msit.go.kr/bbs/view.do?sCode=user&mId=307&mPid=208&bbsSeqNo=94&nttSeqNo=" + no,
                             d, "", "보도자료"))
            urls.append(out[-1]["url"])
        if not got or last < ctx["cutoff"] or all(u in ctx["known"] for u in urls):
            break
        time.sleep(0.3)
    return out


def fetch_spri(src: dict, ctx: dict) -> list:
    """소프트웨어정책연구소 연구자료(이슈리포트·연구보고서 등) — 서버가 그려 주는 카드 목록. 태그를 설명으로 쓴다."""
    out = []
    for page in range(1, src.get("pages", 6) + 1):
        r = _get("https://www.spri.kr/posts", params={"code": "data_all", "data_page": page})
        got, last, urls = 0, "", []
        for box in _soup(r).select("div.box"):
            a = box.select_one(".title a[href*='/posts/view/']")
            d = parse_date(_txt(box.select_one(".data_list_area")))
            if not a or not d:
                continue
            got += 1
            last = d
            kind = _txt(box.select_one(".mark_list_area .bg_c1"))
            tags = " ".join(_txt(x) for x in box.select(".tag_list_area a"))
            out.append(_item(src, _txt(a), urljoin("https://www.spri.kr", a["href"].split("&")[0]), d, tags, kind))
            urls.append(out[-1]["url"])
        if not got or last < ctx["cutoff"] or all(u in ctx["known"] for u in urls):
            break
        time.sleep(0.3)
    return out


def fetch_kisdi(src: dict, ctx: dict) -> list:
    """정보통신정책연구원 — 간행물 유형별 최신 목록. 항목의 goView(게시판, 글번호) 호출로 주소를 만든다."""
    out = []
    for key, (master, name) in src["boards"].items():
        r = _get("https://www.kisdi.re.kr/report/list.do", params={"key": key, "arrMasterId": master})
        for a in _soup(r).select("a[onclick*=goView]"):
            m = re.search(r"goView\('(\d+)',\s*'(\d+)'", a.get("onclick", ""))
            t = _txt(a)
            d = parse_date(t.split("발행일")[-1]) if "발행일" in t else ""
            if not m or not d:
                continue
            title = re.split(r"\s+(?:저자|발행일)\s", t + " ", maxsplit=1)[0].strip()
            out.append(_item(src, title, "https://www.kisdi.re.kr/report/view.do?key=%s&masterId=%s&arrMasterId=%s&artId=%s" %
                             (key, m[1], m[1], m[2]), d, "", name))
        time.sleep(0.3)
    return out


def fetch_kiri(src: dict, ctx: dict) -> list:
    """보험연구원 정기간행물(포커스·글로벌 이슈·CEO Report 등) — 목록 한 쪽에 제목·저자·발간일이 같이 나온다."""
    out = []
    for cat, name in src["boards"].items():
        r = _get("https://www.kiri.or.kr/publication/list.do", params={"catId": cat})
        seen = set()
        for a in _soup(r).select("a[href*='docId=']"):
            t = _txt(a)
            doc = parse_qs(urlparse(a["href"]).query).get("docId", [""])[0]
            d = parse_date(t)
            if not doc or not d or "저자" not in t or doc in seen:
                continue
            seen.add(doc)
            out.append(_item(src, t.split("저자")[0].strip(), "https://www.kiri.or.kr/publication/list.do?catId=%s&docId=%s" % (cat, doc),
                             d, "", name))
        time.sleep(0.3)
    return out


def fetch_wfri(src: dict, ctx: dict) -> list:
    """우리금융경영연구소 연구보고서 — 서버가 그려 주는 카드 목록."""
    out = []
    for page in range(1, src.get("pages", 3) + 1):
        r = _get("https://www.wfri.re.kr/ko/web/research_report/research_report.php", params={"page": page})
        got, last, urls = 0, "", []
        for a in _soup(r).select("a.report-item"):
            idx = parse_qs(urlparse(a.get("href", "")).query).get("idx", [""])[0]
            d = parse_date(_txt(a.select_one(".report-item__date")))
            title = _txt(a.select_one(".report-item__title"))
            if not idx or not d or not title:
                continue
            got += 1
            last = d
            out.append(_item(src, title, "https://www.wfri.re.kr/ko/web/research_report/research_report.php?idx=%s&page_type=view&mode=view" % idx,
                             d, "", _txt(a.select_one(".report-item__category"))))
            urls.append(out[-1]["url"])
        if not got or last < ctx["cutoff"] or all(u in ctx["known"] for u in urls):
            break
        time.sleep(0.3)
    return out


def fetch_hana(src: dict, ctx: dict) -> list:
    """하나금융연구소 — 게시판별 카드 목록(12건/쪽, 쪽은 pageNo). 같은 글이 여러 게시판에 나오므로 글번호로 주소를 하나로 만든다."""
    out, seen = [], set()
    for board, name in src["boards"].items():
        menu, tab = board.split("/")
        for page in range(1, src.get("pages", 3) + 1):
            r = _get("https://www.hanaif.re.kr/boardList.do", params={"menuId": menu, "tabMenuId": tab, "pageNo": page})
            got, last = 0, ""
            for li in _soup(r).select("ul.listType01 > li"):
                a = li.select_one("a.txtBox")
                m = re.search(r"hmpeSeqNo=(\d+)", (a.get("href") if a else "") or "")
                d = parse_date(_txt(li.select_one(".date")))
                title = _txt(li.select_one(".tit"))
                if not m or not d or not title:
                    continue
                got += 1
                last = d
                if m[1] in seen:
                    continue
                seen.add(m[1])
                out.append(_item(src, title, "https://www.hanaif.re.kr/boardDetail.do?hmpeSeqNo=%s&menuId=MN1000&tabMenuId=N" % m[1],
                                 d, _txt(li.select_one(".txt")), (_txt(li.select_one(".topic")) or name)))
            if not got or last < ctx["cutoff"]:
                break
            time.sleep(0.3)
    return out


def fetch_ey(src: dict, ctx: dict) -> list:
    """EY한영 인사이트 — 목록 카드의 주소를 모아, 새 주소만 상세 페이지의 제목·설명·최초 게재일을 읽는다."""
    r = _get(src["url"])
    hrefs = []
    for a in _soup(r).select("div.up-content-grid__list-item a[href]"):
        h = urljoin(r.url, a["href"])
        if h not in hrefs:
            hrefs.append(h)
    out, miss = [], 0
    for u in hrefs[: src.get("limit", 80)]:
        if u in ctx["known"]:
            out.append(_item(src, "", u, ""))
            continue
        try:
            s = _soup(_get(u, tries=1, timeout=20))
        except FetchError:
            miss += 1
            continue
        d = parse_date(_meta(s, "dateuser") or _meta(s, "firstpublishdate"))      # firstpublishdate는 섹션 전체가 같은 날(2025-03-19)이라 쓸 수 없다
        out.append(_item(src, _meta(s, "og:title") or (s.title.string if s.title else ""), u, d,
                         _meta(s, "og:description", "description")))
        time.sleep(0.2)
    if miss:
        print("  · %s: 상세 %d건 읽지 못함" % (src["id"], miss))
    return out


def fetch_bing(src: dict, ctx: dict) -> list:
    """직접 읽을 수 없는 기관(PwC 등)의 보고서 발간 '보도'를 Bing News RSS로 잡는다. 결과는 기관 보고서가 아니라 기사다."""
    out = []
    must = [m.lower() for m in src.get("must", [])]
    for q in src["queries"]:
        r = _get("https://www.bing.com/news/search", params={"q": q, "format": "rss", "setmkt": src.get("mkt", "ko-KR"),
                                                                "freshness": "Month"})
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            raise FetchError("RSS 아님")
        for it in root.iter("item"):
            link = it.findtext("link") or ""
            url = unquote(parse_qs(urlparse(link).query).get("url", [""])[0])
            if not url.startswith("http"):
                continue
            title = H.unescape((it.findtext("title") or "").strip())
            desc = _plain(it.findtext("description") or "")
            if must and not any(m in (title + " " + desc).lower() for m in must):
                continue
            press = ""
            for ch in it:
                if _local(ch.tag) == "Source":
                    press = (ch.text or "").strip()
            out.append(_item(src, title, url, parse_date(it.findtext("pubDate") or ""), desc, press))
        time.sleep(0.5)
    return out


ADAPTERS = {"fsec": fetch_fsec, "fsc": fetch_fsc, "fss": fetch_fss, "sitemap": fetch_sitemap, "rss": fetch_rss,
            "kcmi": fetch_kcmi, "kisa": fetch_kisa, "ey": fetch_ey, "bing": fetch_bing,
            "table": fetch_table, "nia": fetch_nia, "msit": fetch_msit, "spri": fetch_spri, "kisdi": fetch_kisdi,
            "kiri": fetch_kiri, "wfri": fetch_wfri, "hana": fetch_hana}


# ---------------------------------------------------------------- 선별
# 핵심어 — AI와 디지털 기술·디지털 금융 자체를 가리키는 말만 둔다. **제목에** 있어야 통과한다.
#   설명에만 있는 경우(한국은행 요약문 속 'AI', 월간 산업동향 속 '데이터센터')는 주제가 아니라 스치는 말이라 뺀다.
#   보안·개인정보·보이스피싱·전자금융·ICT·결제·플랫폼·데이터·로봇·자동화는 일부러 뺐다 — 그 말만 있는 글(개인정보위 인사발령,
#   보이스피싱 주의보, ICT 수출입 동향)이 보고서 목록의 절반을 채웠다. 가상자산·crypto도 뺐다 — 불공정거래 고발·접속차단 같은 단속 공지뿐이었다. 제목에 AI·디지털이 같이 있으면 그 단어로 통과한다.
_CORE_KO = [
    "인공지능", "생성형", "에이전트", "에이전틱", "초거대", "머신러닝", "딥러닝", "챗봇", "챗GPT", "지능정보", "슈퍼컴퓨터",
    "디지털", "클라우드", "데이터센터", "빅데이터", "사물인터넷", "메타버스", "양자", "망분리",
    "블록체인", "스테이블코인", "토큰증권", "토큰화", "예금토큰", "분산원장",
    "핀테크", "오픈뱅킹", "마이데이터", "로보어드바이저", "레그테크", "섭테크", "텍스트마이닝",
]
_CORE_KO_RX = re.compile("|".join(map(re.escape, _CORE_KO)) +
                         r"|(?<![A-Za-z])(?:AI|LLM|SLM|GPU|NPU|IoT|API|RAG|DX|AX|CBDC|DLT|MCP|RPA|OCR|GPT|ChatGPT|SaaS)(?![A-Za-z])")
_CORE_EN_RX = re.compile(
    r"artificial intelligence|generative|agentic|machine learning|deep learning|large language|\bdigital|fintech|"
    r"blockchain|tokeni[sz]|stablecoin|quantum|\bcloud\b|open banking|\bAI\b|\bLLMs?\b|"
    r"\bDLT\b|\bCBDC|\bregtech|\bsuptech|chatgpt|supercomput", re.I)
_FIN_RX = re.compile(r"금융|은행|보험|증권|카드|자본시장|결제|대출|펀드|자산운용|여신|핀테크|가상자산|토큰증권|스테이블|예금|신용|"
                     r"bank|financ|insur|payment|securit|capital market|fintech|crypto|stablecoin|CBDC|lending|credit", re.I)
_REPORT_RX = re.compile(r"보고서|리포트|백서|가이드라인|로드맵|실태조사|통계|연구용역|전망|\breport\b|\bpaper\b|\boutlook\b|\bsurvey\b|\bwhite ?paper", re.I)
_NO_CORE = "제목에 AI·디지털 핵심어 없음"
# 핵심어가 있어도 싣지 않는 주제 — 암호·보안 쪽 양자 이야기는 AI·디지털 동향이 아니다(양자컴퓨터·양자 기술 자체는 남긴다).
_EXCLUDE_TOPIC_RX = re.compile(r"양자\s*내성|양자\s*암호|양자\s*키|양자\s*보안|양자\s*난수|\bPQC\b|post[- ]quantum|quantum[- ](?:safe|resistant|secure|proof)|"
                               r"quantum\s+(?:key|cryptograph|random)|\bQKD\b", re.I)
_TOPIC_OFF = "제외 주제(양자내성암호 등 암호·보안)"
_KIND_OFF = "%s는 싣지 않음(보고서 위주 설정)"
# 기사 제목 끝의 ': Report'는 '…라고 보도했다'는 뜻이지 보고서 이름이 아니다('Accenture weighs $1.5 billion sale: Report').
_NEWS_TAIL_RX = re.compile(r"[:：,]\s*reports?\s*$", re.I)


def judge(it: dict, src: dict) -> tuple:
    """→ (통과 여부, 일치 단어 목록, 사유). 사유는 제외일 때만 쓴다."""
    title = it["title"]
    if src.get("need") and (not re.search(src["need"], title) or _NEWS_TAIL_RX.search(title)):         # 검색(보도) 수집원: **제목에** 보고서·발간 소식 단어가 있어야 한다(설명까지 보면 실적·제휴·인사 기사가 섞인다)
        return False, [], "제목에 보고서 단어 없음(보도)"
    if _EXCLUDE_TOPIC_RX.search(title):
        return False, [], _TOPIC_OFF
    hits = [m.group(0) for m in _CORE_KO_RX.finditer(title)] + [m.group(0) for m in _CORE_EN_RX.finditer(title)]
    tags = list(dict.fromkeys(h.strip() for h in hits))
    if tags:
        return True, tags[:4], ""
    return False, [], _NO_CORE


def classify(it: dict, src: dict) -> None:
    both = it["title"] + " " + it.get("desc", "")
    it["finance"] = bool(src.get("finance")) or bool(_FIN_RX.search(both))
    kind = src.get("kind", "보고서")
    if kind == "press":                                    # 보도자료는 '보고서·가이드라인·실태조사' 단어가 있을 때만 보고서로 본다
        kind = "보고서" if _REPORT_RX.search(it["title"]) else "정책발표"
    it["kind"] = kind


def make_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- 저장소
def _store_path(root: str) -> str:
    return os.path.join(root, STORE_NAME)


def load_store(root: str = DATA_DIR) -> dict:
    try:
        with open(_store_path(root), encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    d.setdefault("items", [])
    d.setdefault("dropped", [])
    d.setdefault("sources", {})
    return d


def save_store(d: dict, root: str = DATA_DIR) -> None:
    os.makedirs(root, exist_ok=True)
    tmp = _store_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _store_path(root))


# ---------------------------------------------------------------- 실행
def _run_source(src: dict, ctx: dict) -> tuple:
    t0 = time.time()
    try:
        items = ADAPTERS[src["type"]](src, ctx)
        return src, items, "", time.time() - t0
    except FetchError as e:
        return src, [], str(e), time.time() - t0
    except Exception as e:                                  # 어댑터 하나의 버그가 전체를 멈추지 않게
        return src, [], "%s: %s" % (type(e).__name__, str(e)[:80]), time.time() - t0


_KIND_PRI = {"보고서": 0, "정책발표": 1, "보도": 2}


def _norm_title(t: str) -> str:
    return re.sub(r"[\W_]+", "", (t or "").lower())


def merge_same_title(items: list, window_days: int = 14) -> list:
    """다른 기관이 같은 제목으로 낸 것(금융위·금감원 공동 보도자료, FSB 보도자료+간행물)은 한 장으로 합치고 나머지는 also에 남긴다.
    보고서 > 정책발표 > 보도 순으로 대표를 고른다."""
    groups: dict = {}
    for i in items:
        groups.setdefault(_norm_title(i["title"]), []).append(i)
    out = []
    for g in groups.values():
        g.sort(key=lambda i: (_KIND_PRI.get(i["kind"], 9), i["date"], i["first_seen"]))
        keeps: list = []
        for it in g:
            home = next((k for k in keeps if abs((datetime.strptime(k["date"], "%Y-%m-%d") -
                                                  datetime.strptime(it["date"], "%Y-%m-%d")).days) <= window_days), None)
            if home is None:
                keeps.append(it)
                continue
            also = {x["url"]: x for x in home.get("also", [])}
            also[it["url"]] = {"org": it["org"], "url": it["url"]}
            for x in it.get("also", []):
                also[x["url"]] = x
            home["also"] = list(also.values())
        out += keeps
    return out


def run(cfg: dict, root: str = DATA_DIR, only=None, lookback=None, now=None) -> dict:
    rc = cfg.get("reports", {})
    now = now or datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    default_days = lookback or rc.get("lookback_days", 180)
    store = load_store(root)
    by_id = {i["id"]: i for i in store["items"]}
    dropped = {d["id"]: d for d in store["dropped"]}
    known = {i["url"] for i in store["items"]} | {d["url"] for d in store["dropped"]}
    merged = {make_id(x["url"]) for i in store["items"] for x in i.get("also", [])}      # 다른 기관 항목에 합쳐진 주소
    srcs = [s for s in rc.get("sources", []) if s.get("enabled", True) and (not only or s["id"] in only)]

    def cutoff_of(src: dict) -> str:
        return (now - timedelta(days=lookback or src.get("lookback_days", default_days))).strftime("%Y-%m-%d")

    # 선별 기준을 바꾼 뒤에도 이미 저장된 항목이 남지 않도록 다시 판정한다. 탈락한 항목은 사유와 함께 제외 기록으로 옮긴다(조용히 사라지지 않는다).
    excl_kinds = set(rc.get("exclude_kinds") or [])
    src_by_id = {s["id"]: s for s in rc.get("sources", [])}
    n_rejudged = 0
    for iid, old in list(by_id.items()):
        src = src_by_id.get(old.get("src"))
        if not src:
            continue
        ok, tags, reason = judge(old, src)
        if ok and old.get("kind") in excl_kinds:
            ok, reason = False, _KIND_OFF % old["kind"]
        if ok:
            old["tags"] = tags                      # 새 기준의 일치 단어로 갱신
        else:
            n_rejudged += 1
            dropped[iid] = {"id": iid, "org": old["org"], "title": old["title"], "url": old["url"], "date": old["date"],
                            "reason": reason}
            del by_id[iid]
    if n_rejudged:
        print("  기준 재적용: 저장된 %d건을 제외 기록으로 옮김" % n_rejudged)

    print("보고서 수집: %d개 수집원 (기본 %d일 이내)" % (len(srcs), default_days))
    with ThreadPoolExecutor(max_workers=rc.get("workers", 6)) as ex:
        results = list(ex.map(lambda s: _run_source(s, {"cutoff": cutoff_of(s), "known": known}), srcs))

    n_new = n_drop = n_old = 0
    for src, items, err, sec in results:
        cutoff = cutoff_of(src)
        st = {"org": src["org"], "ok": not err, "n": len(items), "error": err, "at": now.strftime("%Y-%m-%d %H:%M")}
        if err and store["sources"].get(src["id"], {}).get("last_ok"):
            st["last_ok"] = store["sources"][src["id"]]["last_ok"]
        elif not err:
            st["last_ok"] = st["at"]
        store["sources"][src["id"]] = st
        print("  %s %-10s %3d건 %4.1fs %s" % ("✗" if err else "✓", src["id"], len(items), sec, err))
        for it in items:
            if not it["url"]:
                continue
            iid = make_id(it["url"])
            it["id"] = iid
            old = by_id.get(iid)
            if iid in merged:
                continue
            if old and not it["title"]:                     # 사이트맵류: 이미 저장된 항목은 제목을 다시 읽지 않았다
                continue
            if not it["title"]:
                continue
            if it["date"] and it["date"] < cutoff:
                n_old += 1
                continue
            ok, tags, reason = judge(it, src)
            if not ok:
                if not old:
                    n_drop += iid not in dropped
                    dropped[iid] = {"id": iid, "org": it["org"], "title": it["title"], "url": it["url"],
                                    "date": (dropped.get(iid) or {}).get("date") or it["date"] or today, "reason": reason}
                continue
            classify(it, src)
            if it["kind"] in excl_kinds:                      # 정책 발표 등 싣지 않기로 한 구분 — 사유와 함께 제외 기록에 남긴다
                if not old:
                    n_drop += iid not in dropped
                    dropped[iid] = {"id": iid, "org": it["org"], "title": it["title"], "url": it["url"],
                                    "date": (dropped.get(iid) or {}).get("date") or it["date"] or today,
                                    "reason": _KIND_OFF % it["kind"]}
                    continue
                by_id.pop(iid, None)
                dropped[iid] = {"id": iid, "org": it["org"], "title": it["title"], "url": it["url"], "date": old["date"],
                                "reason": _KIND_OFF % it["kind"]}
                continue
            if it["date"]:
                date, est = it["date"], False
            elif old:
                date, est = old["date"], old.get("date_est", True)
            else:
                date, est = today, True                      # 게재일을 알 수 없는 항목은 처음 본 날로 두고 '(수집일)'로 표시
            rec = {"id": iid, "org": it["org"], "src": it["src"], "region": it["region"], "kind": it["kind"],
                   "title": it["title"], "url": it["url"], "date": date, "date_est": est, "desc": it["desc"],
                   "sub": it["sub"], "finance": it["finance"], "tags": tags,
                   "first_seen": (old or {}).get("first_seen") or today}
            if old and old.get("also"):
                rec["also"] = old["also"]
            if old and old.get("title") == rec["title"]:               # 번역은 제목·설명이 같을 때만 이어 쓴다
                for k in ("title_ko", "tr_tries"):
                    if k in old:
                        rec[k] = old[k]
                if old.get("desc") == rec["desc"] and "desc_ko" in old:
                    rec["desc_ko"] = old["desc_ko"]
            if not old:
                n_new += 1
            by_id[iid] = rec
            dropped.pop(iid, None)

    kept = merge_same_title(list(by_id.values()))
    # 제외 기록은 가장 긴 조회 기간만큼 보관한다 — 더 일찍 지우면 사이트맵류가 같은 주소를 매 실행 다시 읽는다
    keep_from = (now - timedelta(days=max([default_days] + [s.get("lookback_days", 0) for s in srcs]))).strftime("%Y-%m-%d")
    store["items"] = sorted(kept, key=lambda i: (i["date"], i["first_seen"]), reverse=True)
    kept_ids = {i["id"] for i in kept}
    store["dropped"] = sorted((d for d in dropped.values() if d["date"] >= keep_from and d["id"] not in kept_ids),
                              key=lambda d: d["date"], reverse=True)
    store["updated"] = now.strftime("%Y-%m-%d %H:%M")
    save_store(store, root)
    print("완료: 신규 %d건 · 누적 %d건 · 제외 기록 %d건(이번 신규 %d) · 기간 밖 %d건" %
          (n_new, len(store["items"]), len(store["dropped"]), n_drop, n_old))
    return store


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="쉼표로 구분한 수집원 id")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--out", default=None)
    ap.add_argument("--lookback", type=int, default=None)
    a = ap.parse_args(argv)
    with open("config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not cfg.get("reports", {}).get("enabled", True):
        print("reports.enabled=false — 건너뜀")
        return 0
    store = run(cfg, a.data_dir, set(a.only.split(",")) if a.only else None, a.lookback)
    if cfg.get("reports", {}).get("translate", {}).get("enabled", True):
        try:                                                           # 번역이 실패해도 수집 결과와 페이지는 그대로 낸다(영문 표시)
            import reports_translate
            reports_translate.translate_store(store, cfg)
            save_store(store, a.data_dir)
        except Exception as e:
            print("  ⚠ 번역 단계 오류 — 영문 그대로 표시:", str(e)[:100])
    import reports_page
    print("페이지:", reports_page.render(store, cfg, a.out or reports_page.OUT_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
