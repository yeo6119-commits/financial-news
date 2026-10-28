# =============================================================
# outlets.py — 기사 링크 → 언론사 이름
#
# DB의 press 칸은 반영 기사의 약 80%가 비어 있다. 이름을 추측하지 않고 사이트가 스스로 밝힌 이름을 읽는다.
#   - 일반 매체: 홈페이지의 <meta og:site_name> (없으면 <title>)
#   - 네이버 링크: 기사 페이지의 <meta og:article:author> ("전자신문 | 네이버")
# 한 번 읽은 이름은 outlets.json에 저장한다(키: "dom:도메인" / "oid:네이버 매체코드").
# 실행 중에는 새로 나온 키만 회차당 몇 건씩 조회해 채운다 — LLM 토큰은 쓰지 않는다.
# =============================================================
import html as H
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # SSL 오류 매체는 이름만 읽으므로 검증을 생략

PATH = "outlets.json"
_OID = re.compile(r"/article/(\d{3})/|[?&]oid=(\d{3})")
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
_SEP = re.compile(r"\s*[|:·»–—-]\s*|\s{2,}")


def key_of(url):
    """URL → 매체 키. 네이버는 oid, 그 밖엔 도메인. 알 수 없으면 None."""
    url = url or ""
    m = _OID.search(url)
    if m:
        return "oid:" + (m.group(1) or m.group(2))
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return None
    h = re.sub(r"^(www|m)\.", "", m.group(1).lower())
    return None if h.endswith("naver.com") else "dom:" + h


def load(path: str = PATH) -> dict:
    try:
        d = json.load(open(path, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(mapping: dict, path: str = PATH) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(mapping.items())), fh, ensure_ascii=False, indent=0)
        fh.write("\n")


def clean_name(raw):
    """사이트가 알려준 이름을 보기 좋게 다듬는다. 믿을 수 없으면 None."""
    if not raw:
        return None
    s = H.unescape(raw).replace("\\", "").replace("\"", "").replace("'", "").strip()   # \'플래텀\' 같은 따옴표 제거
    s = re.sub(r"\s*\|\s*네이버\s*$", "", s)                  # "전자신문 | 네이버"
    s = re.sub(r"\s*\(\s*[A-Za-z][A-Za-z0-9 .&-]*\)\s*", "", s).strip()   # "컨슈머타임스(Consumertimes)"
    if len(s) > 24 or _SEP.search(s):
        parts = [p.strip() for p in _SEP.split(s) if len(p.strip()) >= 2]
        if not parts:
            return None
        s = min(parts, key=len)                                # '메인 이름 - 긴 슬로건'에서 이름 쪽
    s = s.strip(" -|:·")
    return s if 2 <= len(s) <= 24 else None


def _meta(html: str, *names):
    for n in names:
        pat = re.escape(n)
        m = (re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*?content=["\']([^"\']+)' % pat, html, re.I)
             or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*?(?:property|name)=["\']%s["\']' % pat, html, re.I))
        if m:
            return m.group(1)
    return None


def _get(url, timeout=8):
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.exceptions.SSLError:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False)   # 이름만 읽는 용도
        except requests.RequestException:
            return None
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    if "charset=" not in r.headers.get("content-type", "").lower():
        r.encoding = r.apparent_encoding or r.encoding
    return r.text[:80000]


def fetch_name(key, sample_url):
    """키 하나의 매체 이름을 사이트에서 읽는다. 실패하면 None."""
    if key.startswith("oid:"):
        html = _get(sample_url)
        return clean_name(_meta(html or "", "og:article:author")) if html else None
    host = key[4:]
    html = _get("http://" + host + "/") or _get("https://" + host + "/")
    if not html:
        return None
    name = clean_name(_meta(html, "og:site_name", "application-name"))
    if name:
        return name
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return clean_name(re.sub(r"\s+", " ", m.group(1))) if m else None


def resolve(missing: dict, limit: int = 40, workers: int = 8) -> dict:
    """{키: 대표 URL} 중 최대 limit개를 조회해 {키: 이름}을 돌려준다(찾은 것만)."""
    keys = list(missing)[:limit]
    if not keys:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        names = list(ex.map(lambda k: fetch_name(k, missing[k]), keys))
    return {k: n for k, n in zip(keys, names) if n}


def name_for(url, press, mapping) -> str:
    """표시할 언론사 이름. press가 있으면 그대로, 없으면 매핑에서 찾는다. 모르면 빈 문자열."""
    if press and str(press).strip():
        return str(press).strip()
    k = key_of(url)
    v = mapping.get(k, "") if k else ""
    return v if isinstance(v, str) else ""


FAIL_KEY = "_failed"          # {키: 'YYYY-MM-DD'} — 읽기에 실패한 키는 RETRY_DAYS 뒤에 다시 시도
RETRY_DAYS = 14
_DUP_SQL = ("SELECT url FROM excluded_log WHERE reason LIKE '중복(%대표: %' "
            "OR reason LIKE '기열람(동일 사건%' OR reason LIKE '기열람(본문 재탕:%'")


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _stale(day) -> bool:
    from datetime import date, timedelta
    try:
        return date.fromisoformat(day) <= date.today() - timedelta(days=RETRY_DAYS)
    except (TypeError, ValueError):
        return True


def learn(need: dict, limit: int = 40, path: str = PATH) -> dict:
    """{키: 대표 URL} 중 아직 이름을 모르는 키를 최대 limit개 조회해 outlets.json에 더하고 매핑을 돌려준다.
    실패한 키는 RETRY_DAYS 동안 다시 조회하지 않는다. 조회가 통째로 실패해도 예외를 밖으로 내지 않는다."""
    mapping = load(path)
    failed = mapping.get(FAIL_KEY) if isinstance(mapping.get(FAIL_KEY), dict) else {}
    todo = {k: u for k, u in need.items()
            if k not in mapping and (k not in failed or _stale(failed[k]))}
    if not todo:
        return mapping
    try:
        got = resolve(todo, limit=limit, workers=8)
    except Exception:
        return mapping
    tried = list(todo)[:limit]
    for k in tried:
        if k in got:
            mapping[k] = got[k]
            failed.pop(k, None)
        else:
            failed[k] = _today()
    if failed:
        mapping[FAIL_KEY] = failed
    else:
        mapping.pop(FAIL_KEY, None)
    save(mapping, path)
    print(f"  언론사 이름 조회: {len(tried)}건 중 {len(got)}건 확보 (파일 {len(mapping) - (1 if FAIL_KEY in mapping else 0)}개)")
    return mapping


def refresh(conn, rows, limit: int = 40, path: str = PATH) -> dict:
    """카드·비슷한 기사 링크에서 아직 이름을 모르는 키를 조회해 outlets.json에 더한다."""
    need = {}
    for a in rows:
        if a["press"] and str(a["press"]).strip():
            continue
        u = a["naver_url"] if key_of(a["naver_url"]) else a["original_url"]
        k = key_of(u)
        if k:
            need.setdefault(k, u)
    for (u,) in conn.execute(_DUP_SQL):
        k = key_of(u)
        if k:
            need.setdefault(k, u)
    return learn(need, limit, path)
