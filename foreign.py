# =============================================================
# foreign.py — 해외(영문) 뉴스 트랙
#
# 국내 파이프라인(main.py·Groq·news.db)과 완전히 분리된 별도 실행이다.
#   수집  Bing News RSS(실제 기사 주소를 바로 줌) + Google News RSS(보조: 중계 링크를 풀어야 함)
#   선별  시황·종목 분석성 제목 제외, 관련 주제어 필수, 비슷한 제목 합치기, 하루/회사별 상한
#   본문  실제 기사 페이지에서 추출 — 유료벽 등으로 읽을 수 없으면(짧으면) 건너뜀
#         기사가 대상 회사를 다루는지(제목·본문 앞부분), 같은 사건이 이미 있는지(본문 핵심어)를 확인
#   요약  구독 Claude(claude -p)만 사용해 한국어로 번역·요약 (Groq 한도·국내 실행에 영향 없음)
#   저장  foreign/data/YYYY-MM-DD.json (KST 날짜별, 지우지 않음). 국내 페이지 생성 때 읽어 '해외 영문' 탭에 얹는다.
# 어떤 기사도 조용히 사라지지 않는다 — 걸러진 후보는 사유와 함께 같은 파일의 dropped에 남긴다.
#
# 구글 링크 해독은 짧은 시간에 많이 부르면 429(확인 페이지)로 막힌다(2026-10 실측: 약 90회 뒤 차단).
# 그래서 Bing을 주로 쓰고, 구글은 상한을 두고 연속 실패하면 그 회차에서는 더 부르지 않는다.
# =============================================================
import base64
import collections
import hashlib
import html as H
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
import yaml

import deduplicator as ddp
import extractor as ext
import foreign_store as store
import summarizer as smr

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
DROPPED_PER_REASON = 40        # 사유별로 목록에 남기는 최대 건수 (건수 집계는 전부 센다 — 하루 수백 건이라 목록은 사유별로 자른다)


# ---------------------------------------------------------------- 수집
def _pubdate(s: str) -> str:
    try:
        return parsedate_to_datetime(s or "").astimezone(KST).isoformat()
    except (TypeError, ValueError):
        return ""


def parse_google(xml_text: str) -> list:
    """Google News RSS → [{title, source, source_url, link, pub_date}]. 제목 끝의 ' - 매체명'은 뗀다."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = H.unescape((it.findtext("title") or "").strip())
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(source) - 3].strip()
        out.append({"title": title, "source": source, "link": (it.findtext("link") or "").strip(),
                    "source_url": src_el.get("url", "") if src_el is not None else "",
                    "pub_date": _pubdate(it.findtext("pubDate")), "via": "google"})
    return out


def parse_bing(xml_text: str) -> list:
    """Bing News RSS → 같은 형식. 링크의 url= 파라미터가 실제 기사 주소라 따로 풀 필요가 없다."""
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        link = it.findtext("link") or ""
        url = unquote(parse_qs(urlparse(link).query).get("url", [""])[0])
        if not url.startswith("http"):
            continue
        source = ""
        for ch in it:
            if ch.tag.endswith("Source"):
                source = (ch.text or "").strip()
        out.append({"title": H.unescape((it.findtext("title") or "").strip()), "source": source, "url": url,
                    "source_url": url, "pub_date": _pubdate(it.findtext("pubDate")), "via": "bing"})
    return out


def _get_rss(url: str, params=None):
    for attempt in range(2):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(1.5)
    return None


def fetch_rss(company: dict, fc: dict) -> list:
    """한 회사의 후보를 모든 수집원에서 모은다."""
    items = []
    srcs = fc.get("sources", ["bing"])
    for q in company["queries"]:
        if "bing" in srcs:
            for topic in fc.get("bing_topics", []):
                txt = _get_rss("https://www.bing.com/news/search",
                               {"q": f'"{q}" {topic}', "format": "rss", "setmkt": "en-US", "freshness": "Day"})
                items += parse_bing(txt) if txt else []
                time.sleep(0.5)
        if "google" in srcs:
            gq = f'"{q}" {fc["topic_query"]} when:{fc.get("lookback", "1d")}'
            txt = _get_rss("https://news.google.com/rss/search?q=" + quote(gq) + "&hl=en-US&gl=US&ceid=US:en")
            items += parse_google(txt) if txt else []
    for it in items:
        it["company"] = company["name"]
    return items


# ---------------------------------------------------------------- 선별
def _rx(terms) -> re.Pattern:
    """단어 경계 정규식 — 'stock'이 Stockholm에, 'app'이 apple에 걸리지 않게. 끝이 '-ize' 같은 어간(tokeniz)은 접두 허용."""
    parts = []
    for t in terms:
        e = re.escape(t)
        parts.append(r"(?<![A-Za-z0-9])" + e + (r"[A-Za-z]*" if t.endswith(("iz", "is")) else r"(?![A-Za-z0-9])"))
    return re.compile("|".join(parts), re.I)


class Rules:
    def __init__(self, fc: dict):
        # 은행이 '투자자·주선자'로 등장하는 자금조달·투자유치 기사(은행의 디지털·AI 이야기가 아님). 정규식 그대로 쓴다.
        self.deal = re.compile("|".join(fc.get("deal_title", [])), re.I) if fc.get("deal_title") else None
        self.topic = _rx(fc["topic_terms"])
        self.strong = _rx(fc["strong_terms"])
        self.action = _rx(fc["action_terms"])
        self.noise = _rx(fc["noise_title"])
        self.blocked = tuple(d.lower() for d in fc["blocked_sources"])
        # 회사별 영문 별칭 정규식 (한글 별칭은 영문 본문에 안 나온다)
        self.co_rx = {co["name"]: _rx([a for a in (co.get("aliases") or []) + co.get("queries", []) if re.search(r"[A-Za-z]", a)])
                      for co in fc["companies"]}

    def blocked_source(self, source_url: str) -> bool:
        d = re.sub(r"^https?://(www\.)?", "", (source_url or "").lower()).split("/")[0]
        return any(d == b or d.endswith("." + b) for b in self.blocked)

    def score(self, title: str) -> int:
        return 3 * len(set(m.lower() for m in self.strong.findall(title))) + \
               (2 if self.action.search(title) else 0) + (1 if self.topic.search(title) else 0)

    def companies_in(self, text: str) -> list:
        """텍스트에 등장하는 대상 회사들을 먼저 나온 순서로."""
        hits = []
        for name, rx in self.co_rx.items():
            m = rx.search(text)
            if m:
                hits.append((m.start(), name))
        return [n for _, n in sorted(hits)]


def title_tokens(t: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


_STOP = set("that this with from have will were their would about which they been also more than into after said says other "
            "over such what when where while these those them then some most only just very much many each both your our not "
            "but are for the and has had its can may per via new year last first one two three according report reports".split())


def body_fp(body: str) -> list:
    """같은 사건 판정용 핵심어(본문 앞 2,500자에서 자주 나오는 단어 40개)."""
    cnt = collections.Counter(t for t in re.findall(r"[A-Za-z][A-Za-z0-9&.-]{3,}", body[:2500].lower()) if t not in _STOP)
    return sorted(w for w, _ in cnt.most_common(40))


def fp_overlap(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / max(1, min(len(a), len(b)))


def summary_tokens(summary: str, cfg: dict) -> set:
    """국내 dedup_by_summary와 같은 방식의 요약 핵심어 집합."""
    return ddp.title_tokens(ddp.normalize_title((summary or "").replace("\n", " "), cfg))


def age_problem(c: dict, now, max_age_days: float) -> str:
    """게재일이 없거나 너무 오래됐으면 사유, 괜찮으면 ''. RSS의 기간 옵션(freshness·when:)은 지켜지지 않아 직접 거른다
    (첫 실행에서 2025-10, 2026-08 기사가 들어왔다)."""
    try:
        age = (now - datetime.fromisoformat(c.get("pub_date") or "")).total_seconds() / 86400
    except (TypeError, ValueError):
        return "게재일 불명"
    return "오래된 기사(%d일 전)" % age if age > max_age_days else ""


def prefilter(cands: list, rules: Rules, seen_titles: list, drop) -> list:
    """제목·출처만으로 거를 수 있는 것을 거르고, 비슷한 제목은 하나로 합친다."""
    kept = []
    for c in cands:
        if rules.blocked_source(c.get("source_url") or c.get("url")):
            drop(c, "차단 출처(주가·시황 사이트)"); continue
        if rules.noise.search(c["title"]):
            drop(c, "시황·종목 분석성 제목"); continue
        if rules.deal and rules.deal.search(c["title"]):
            drop(c, "투자·자금조달 기사(은행의 디지털·AI 소식 아님)"); continue
        if not rules.topic.search(c["title"]):
            drop(c, "관련 주제어 없음"); continue
        c["tok"] = title_tokens(c["title"])
        if any(jaccard(c["tok"], t) >= 0.6 for t in seen_titles):
            drop(c, "이미 반영된 기사와 같은 사건(제목)"); continue
        kept.append(c)
    kept.sort(key=lambda c: -rules.score(c["title"]))
    reps = []
    for c in kept:
        twin = next((r for r in reps if jaccard(c["tok"], r["tok"]) >= 0.6), None)
        if twin:
            drop(c, "비슷한 제목(대표: %s)" % twin["title"][:40])
            twin.setdefault("also", []).append(c["company"])
        else:
            reps.append(c)
    return reps


def pick_for_extraction(reps: list, rules: Rules, fc: dict, quota_left: dict, drop) -> list:
    """본문을 실제로 확인할 후보: 회사별 상한 안에서 점수순."""
    per = fc.get("extract_per_company", 6)
    lim = fc.get("extract_limit", 40)
    by_co = {}
    for c in sorted(reps, key=lambda c: -rules.score(c["title"])):
        by_co.setdefault(c["company"], []).append(c)
    chosen = []
    for co, lst in by_co.items():
        if quota_left.get(co, 0) <= 0:
            for c in lst:
                drop(c, "회사 상한(오늘 이미 %d건)" % fc["max_per_company_per_day"])
            continue
        for c in lst[per:]:
            drop(c, "후보 상한(회사별 %d건)" % per)
        chosen += lst[:per]
    chosen.sort(key=lambda c: -rules.score(c["title"]))
    for c in chosen[lim:]:
        drop(c, "후보 상한(전체 %d건)" % lim)
    return chosen[:lim]


# ---------------------------------------------------------------- 링크 해독(구글)·본문
def decode_google_link(link: str):
    """Google News 중계 주소 → 실제 기사 주소. 실패하면 None."""
    gid = link.split("/")[-1].split("?")[0]
    try:                                    # 구형: base64 안에 주소가 그대로 있다
        s = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4)).decode("latin1")
        if s.startswith("\x08\x13\x22"):
            s = s[3:]
        if s.endswith("\xd2\x01\x00"):
            s = s[:-3]
        b = bytearray(s, "latin1")
        s = s[2:b[0] + 1] if b[0] >= 0x80 else s[1:b[0] + 1]
        if s.startswith("http"):
            return s
    except Exception:
        pass
    try:                                    # 신형: batchexecute로 서명을 받아 해독
        page = requests.get(f"https://news.google.com/articles/{gid}", headers=UA, timeout=20).text
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sg and ts):
            return None                     # 429 확인 페이지 등 — 막힘
        inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                                            None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                            gid, int(ts.group(1)), sg.group(1)])
        req = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        res = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", data="f.req=" + quote(req),
                            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}, timeout=20)
        url = json.loads(json.loads(res.text.split("\n\n", 1)[1])[0][2])[1]
        return url if url.startswith("http") else None
    except Exception:
        return None


def fetch_body(url: str):
    html = ext._get(url)
    return ext._extract_generic(html) if html else None


# ---------------------------------------------------------------- 요약
def claude_cfg(cfg: dict) -> dict:
    """구독 Claude(CLI)만 쓰도록 강제한다 — Groq·API 키 경로 차단."""
    import copy
    c = copy.deepcopy(cfg)
    cf = c.setdefault("summarizer", {}).setdefault("claude_fallback", {})
    cf["enabled"] = True
    cf["transport"] = "cli"
    return c


def claude_ready(ccfg: dict) -> bool:
    """구독 Claude를 쓸 수 있는가. Actions에서는 토큰이 있어야 하고(없으면 호출이 전부 인증 오류),
    로컬에서는 CLI가 있으면 된다(키체인 로그인)."""
    import os
    if smr._claude_transport(ccfg["summarizer"]["claude_fallback"]) != "cli":
        return False
    if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip():
        return False
    return True


def summarize_with_claude(art: dict, cfg: dict) -> bool:
    s = cfg["summarizer"]
    body = smr.compact_body(art["body"], s.get("body_chars_en", 2000))
    prompt = smr.EN_NOTE + smr.PROMPT.format(title=art["title"], body=body)
    ok = smr._summarize_claude(art, prompt, body, cfg)
    if not ok:
        art["fail"] = "요약 실패(%s)" % (smr.CLAUDE_LAST_ERR or "알 수 없음")
    return ok


# ---------------------------------------------------------------- 제목 번역
TITLE_PROMPT = """다음 영문 기사 제목을 자연스러운 한국어 제목 한 줄로 번역하세요.
- 회사명·제품명·고유명사는 한국에서 쓰는 표기(JP모건, 골드만삭스 등)로 쓰고, 확실하지 않으면 영문 그대로 둡니다.
- 수치·날짜·따옴표 안 말은 그대로 옮기고, 의미를 더하거나 빼지 않습니다. 해석·전망을 붙이지 않습니다.
- 간결하게 씁니다(가능하면 60자 안팎). 제목 뒤에 덧붙은 부제(— 이후)는 빼고 핵심만 옮깁니다.
- 관용구는 직역하지 말고 뜻으로 옮깁니다(예: Reining in X → X를 제한·단속, bank run → 뱅크런, thorn in the side → 골칫거리).
- 번역문 한 줄만 출력합니다(설명·따옴표·'번역:' 없음).

제목: {title}
"""
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9&.'-]*")
_HANGUL = re.compile(r"[가-힣]")


def valid_title_ko(ko: str, en: str) -> str:
    """번역 제목 검증. 통과하면 정리한 문자열, 아니면 ''.
    - 한글이 있어야 하고 한 줄·120자 이하
    - 번역문에 남은 영문 단어는 원제목에 있던 것이어야 한다(없던 고유명사를 지어낸 환각 차단)"""
    ko = (ko or "").strip().splitlines()[0].strip().strip("\"'“”‘’「」 ") if (ko or "").strip() else ""
    ko = re.sub(r"^(번역|제목)\s*[:：]\s*", "", ko)
    if not ko or len(ko) > 120 or len(_HANGUL.findall(ko)) < 2:
        return ""
    if re.search(r"죄송|번역할 수|제공해 주|알려 주|확인해 주|주어진|니다[.!]?$|세요[.!]?$", ko):   # 거절·되묻기 문장은 제목이 아니다
        return ""
    en_low = en.lower()
    for t in _LATIN.findall(ko):
        if len(t) >= 2 and t.lower().strip(".'-") not in en_low:
            return ""
    return ko


def translate_title(title: str, ccfg: dict) -> str:
    """영문 제목 → 한국어 제목(구독 Claude, 호출 1회). 실패하면 ''(화면에는 영문 제목을 쓴다)."""
    c = dict(ccfg["summarizer"]["claude_fallback"])
    c["cli_system"] = "당신은 영한 번역기입니다. 번역한 제목 한 줄만 출력합니다."
    c["cli_model"] = ccfg.get("foreign", {}).get("title_model") or c.get("cli_model", "haiku")   # 제목은 짧아 한도 부담이 작다 — 관용구 번역은 더 큰 모델이 낫다
    if smr._CLAUDE_DEAD:
        return ""
    for attempt in range(2):
        try:
            raw, tin, tout = smr._claude_call_cli(TITLE_PROMPT.format(title=title), c)
        except smr._ClaudeFatal as e:
            smr.CLAUDE_LAST_ERR = str(e); smr._CLAUDE_DEAD = True
            return ""
        except smr._ClaudeBusy as e:
            time.sleep(e.wait); continue
        except Exception:
            time.sleep(2); continue
        smr.CLAUDE_USAGE["calls"] += 1; smr.CLAUDE_USAGE["in"] += tin; smr.CLAUDE_USAGE["out"] += tout
        return valid_title_ko(raw, title)               # 형식·환각 실패는 같은 프롬프트로 다시 불러도 같다 — 재시도 안 함
    return ""


# ---------------------------------------------------------------- 전체 실행
def run(cfg: dict, root: str = store.DATA_DIR, now=None, rss_fn=None, body_fn=None, decode_fn=None,
        summarize_fn=None, check_claude=None, title_fn=None) -> dict:
    fc = cfg["foreign"]
    if not fc.get("enabled", True):
        print("해외 영문 트랙: 꺼져 있음"); return {}
    now = now or datetime.now(KST)
    day = now.strftime("%Y-%m-%d")
    rss_fn = rss_fn or fetch_rss
    body_fn = body_fn or fetch_body
    decode_fn = decode_fn or decode_google_link
    ccfg = claude_cfg(cfg)
    if check_claude is None:
        check_claude = summarize_fn is None          # 실제 실행에서만 구독 Claude 유무를 확인한다(시험에선 가짜 요약기 주입)
    summarize_fn = summarize_fn or (lambda a: summarize_with_claude(a, ccfg))
    title_fn = title_fn or (lambda t: translate_title(t, ccfg))

    data = store.load_day(day, root)
    left_day = fc["max_per_day"] - len(data["articles"])
    print(f"해외 영문 트랙 · {day} · 오늘 이미 {len(data['articles'])}건 / 하루 상한 {fc['max_per_day']}건")
    if left_day <= 0:
        print("  오늘 상한에 도달 — 종료"); return {"added": 0}
    quota_run = min(fc.get("max_per_run", 10), left_day)

    # 요약에 쓸 구독 Claude를 먼저 확인한다 — 없으면 헛수고(본문 수집)를 하지 않는다.
    if check_claude and not claude_ready(ccfg):
        print("  ⚠ 구독 Claude(CLI·CLAUDE_CODE_OAUTH_TOKEN)가 없어 요약할 수 없음 — 수집·저장을 건너뜁니다.")
        return {"added": 0, "no_claude": True}

    dropped = data["dropped"]

    dkeys = data.setdefault("drop_keys", {})        # 후보 해시 → 사유 종류: 그날 제외된 '서로 다른' 후보 수를 사유별로 세기 위한 것

    def rkind(why):
        return why.split("(")[0].split(":")[0]

    def drop(c, why):
        # 하루 3번 돌면 같은 후보가 매번 제외된다 — 같은 주소·제목은 마지막 사유 하나만 남긴다
        key = c.get("url") or c.get("link", "") or c["title"]
        dkeys[hashlib.sha1(key.encode()).hexdigest()[:12]] = rkind(why)
        dropped[:] = [d for d in dropped if (d.get("url") or d["title"]) != key]
        if sum(1 for d in dropped if rkind(d["reason"]) == rkind(why)) < DROPPED_PER_REASON:
            dropped.append({"title": c["title"], "company": c["company"], "press": c.get("source", ""),
                            "url": c.get("url") or c.get("link", ""), "reason": why, "at": now.isoformat(timespec="seconds")})

    rules = Rules(fc)
    recent = store.load_recent(7, root)                  # 최근 7일 반영분 — 같은 주소·사건은 다시 넣지 않는다
    seen_urls = {a["url"] for a in recent}
    seen_titles = [title_tokens(a["title"]) for a in recent]
    seen_fps = [a["fp"] for a in recent if a.get("fp")]

    companies = fc["companies"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        raw = [it for lst in ex.map(lambda co: rss_fn(co, fc), companies) for it in lst]
    print(f"  수집: {len(raw)}건 ({len(companies)}개 회사, 수집원 {','.join(fc.get('sources', []))})")
    fresh_raw = []
    for c in raw:
        why = age_problem(c, now, fc.get("max_age_days", 3))
        drop(c, why) if why else fresh_raw.append(c)
    if len(fresh_raw) != len(raw):
        print(f"  게재일 {fc.get('max_age_days', 3)}일 초과·불명으로 제외: {len(raw) - len(fresh_raw)}건")
    # 이미 카드로 반영된 주소는 조용히 건너뛴다 — 제외가 아니라 이미 화면에 있는 기사라서 제외 목록·집계에 넣지 않는다
    raw = [c for c in fresh_raw if not c.get("url") or c["url"] not in seen_urls]

    quota_left = {co["name"]: fc["max_per_company_per_day"] - sum(1 for a in data["articles"] if a["company"] == co["name"])
                  for co in companies}
    reps = prefilter(raw, rules, seen_titles, drop)
    chosen = pick_for_extraction(reps, rules, fc, quota_left, drop)
    print(f"  제목 선별 후 후보 {len(reps)}건 → 본문 확인 대상 {len(chosen)}건")

    added, g_fail, g_used, g_off = [], 0, 0, False
    stats = collections.Counter()
    for idx, c in enumerate(chosen):
        if len(added) >= quota_run:
            drop(c, "이번 실행 상한(%d건)" % quota_run); continue
        if quota_left.get(c["company"], 0) <= 0:
            drop(c, "회사 상한(하루 %d건)" % fc["max_per_company_per_day"]); continue
        if not c.get("url"):                              # 구글 중계 링크 — 상한·차단기 안에서만 해독
            if g_off or g_used >= fc.get("google_decode_limit", 15):
                drop(c, "구글 링크 해독 제한(차단 방지)"); continue
            g_used += 1
            time.sleep(1.2)
            c["url"] = decode_fn(c["link"])
            if not c["url"]:
                g_fail += 1
                if g_fail >= 3:
                    g_off = True
                    print("  ⚠ 구글 링크 해독이 연속 실패 — 이번 실행에서는 구글 후보를 쓰지 않음(차단 가능성)")
                drop(c, "구글 링크 해독 실패"); continue
            g_fail = 0
        if c["url"] in seen_urls or any(a["url"] == c["url"] for a in data["articles"]):
            drop(c, "이미 반영된 주소"); continue
        body = body_fn(c["url"])
        if not body or len(body) < fc.get("min_body_chars", 400):
            drop(c, "본문 접근 불가(유료벽·차단·짧음 %d자)" % len(body or "")); stats["no_body"] += 1; continue
        if not smr.is_english(body):
            drop(c, "영문 본문이 아님"); continue
        # 대상 회사가 주제인가: 제목, 없으면 본문 앞부분에 등장해야 한다
        mentioned = rules.companies_in(c["title"]) or rules.companies_in(body[:600])
        if not mentioned:
            drop(c, "대상 회사가 주제가 아님"); continue
        company = c["company"] if c["company"] in mentioned else mentioned[0]
        if quota_left.get(company, 0) <= 0:
            drop(c, "회사 상한(하루 %d건)" % fc["max_per_company_per_day"]); continue
        fp = body_fp(body)
        twin = next((a for a in added if fp_overlap(fp, a["fp"]) >= fc.get("event_overlap", 0.5)), None)
        if twin or any(fp_overlap(fp, f) >= fc.get("event_overlap", 0.5) for f in seen_fps):
            drop(c, "같은 사건(본문 유사)" + (": " + twin["title"][:40] if twin else ""))
            if twin:
                twin.setdefault("also", []).append(company)
            continue
        art = {"title": c["title"], "company": company, "body": body}
        if not summarize_fn(art):
            drop(c, art.get("fail") or "요약 실패")
            if smr._CLAUDE_DEAD:                          # 인증·한도 오류 — 이번 실행에서는 더 부르지 않는다
                print("  ⚠ 구독 Claude 오류로 중단:", smr.CLAUDE_LAST_ERR)
                stats["claude_dead"] = 1
                for rest in chosen[idx + 1:]:
                    drop(rest, "구독 Claude 오류로 미처리(다음 실행에서 다시 시도)")
                break
            continue
        # 2차 중복: 같은 사건을 다른 제목으로 쓴 기사는 본문 핵심어로 못 잡는 경우가 있어(실측) 요약 겹침으로 한 번 더 본다.
        #   같은 회사가 관련된 기사끼리만 묶는다(국내 요약 중복과 같은 원칙).
        stok = summary_tokens(art["summary"], cfg)
        thr = fc.get("event_summary_overlap", 0.35)
        twin2 = next((a for a in data["articles"] if (a["company"] == company or company in a.get("also", []) or a["company"] in mentioned)
                      and ddp.token_overlap(stok, summary_tokens(a["summary"], cfg)) >= thr), None)
        if twin2:
            drop(c, "같은 사건(요약 유사): " + twin2["title"][:40])
            twin2.setdefault("dups", []).append({"press": c.get("source", ""), "title": c["title"], "url": c["url"]})
            continue
        if any(ddp.token_overlap(stok, summary_tokens(a["summary"], cfg)) >= thr and (a["company"] == company or company in a.get("also", []))
               for a in recent):
            drop(c, "같은 사건(최근 7일 반영분과 요약 유사)")
            continue
        title_ko = title_fn(c["title"])
        rec = {"id": hashlib.sha1(c["url"].encode()).hexdigest()[:16], "company": company, "title": c["title"],
               "title_ko": title_ko,
               "press": c.get("source", ""), "url": c["url"], "pub_date": c["pub_date"], "summary": art["summary"],
               "also": [x for x in dict.fromkeys(c.get("also", []) + mentioned) if x != company],
               "fp": fp, "collected_at": now.isoformat(timespec="seconds")}
        data["articles"].append(rec); added.append(rec)
        dropped[:] = [d for d in dropped if d.get("url") != c["url"]]      # 앞 실행에서 제외됐다가 이번에 들어온 기사
        dkeys.pop(hashlib.sha1(c["url"].encode()).hexdigest()[:12], None)
        quota_left[company] -= 1
        print(f"  + [{company}] {c['title'][:60]}")
    # 앞 실행에서 제목 번역이 실패한 오늘 기사는 다시 시도한다(기사당 최대 2번, 한 실행 10건까지)
    fresh = {r["id"] for r in added}
    for a in [x for x in data["articles"] if not x.get("title_ko") and x["id"] not in fresh and x.get("title_tries", 1) < 2][:10]:
        a["title_ko"] = title_fn(a["title"])
        if not a["title_ko"]:
            a["title_tries"] = a.get("title_tries", 1) + 1
    store.save_day(day, data, root)
    print(f"  반영 {len(added)}건 (오늘 누적 {len(data['articles'])}/{fc['max_per_day']}) · 본문 접근 불가 {stats['no_body']}건 · "
          f"구글 해독 {g_used}회 · 제외 기록 {len(dropped)}건")
    return {"added": len(added), "total_today": len(data["articles"])}


def main() -> int:
    with open("config.yaml", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    res = run(cfg)
    try:                                             # 페이지 생성 실패가 수집 결과(저장 완료)를 막지 않게
        import foreign_page
        print("  페이지:", foreign_page.build(cfg))
    except Exception as e:
        print("  ⚠ 해외 페이지 생성 실패:", e)
        return 1
    return 2 if (res or {}).get("no_claude") else 0


if __name__ == "__main__":
    sys.exit(main())
