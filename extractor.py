# =============================================================
# extractor.py — 기사 본문 추출 (v2.3)
# 우선순위: 네이버 뉴스 링크 → originallink → 실패 보존
# =============================================================
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

# 범용 본문 추출 폴백 — 매체마다 커스텀 HTML이라 셀렉터 수동 추가는 끝이 없다.
#   보안뉴스·더벨·iM뱅크 등 비제휴 매체가 반복 실패했다(<br> 문단, 자체 div, EUC-KR).
#   설치 안 돼 있어도 동작하도록 선택적 임포트.
try:
    import trafilatura
except ImportError:
    trafilatura = None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# 네이버 뉴스 본문 셀렉터 (일반 / 연예 / 스포츠 구버전)
NAVER_BODY_SELECTORS = ["#dic_area", "#articeBody", "#newsEndContents", "#articleBodyContents"]
NAVER_PRESS_SELECTORS = [".media_end_head_top_logo img", ".press_logo img"]
# 일반 언론사 사이트 본문 후보 (originallink 폴백용) — 구체적인 것부터.
#   '<article>'은 일부러 뺐다(아래 BARE_ARTICLE). 이 태그는 너무 일반적이라 날씨 위젯·'다른 기사'
#   소개문·로그인 바 같은 곁가지에도 쓰인다. 맨 앞에 두고 200자만 넘으면 채택했더니
#   더리포트는 미세먼지 위젯이, 뉴스웨이는 사이드바 다른 기사 소개문이 본문이 되어
#   제목과 전혀 다른 요약이 나갔다(2026-09~11, 8건).
GENERIC_BODY_SELECTORS = [
    "#article-view-content-div", ".article_body", ".news_body",
    "#articleBody", ".article-view", "#news_body_area", ".view_con", "#CmAdContent",
]
BARE_ARTICLE = "article"


def _get(url: str, timeout: int = 10) -> str | None:
    """단발성 접속 실패는 대부분 일시적 WAF/봇차단·해외 접속 지연이다.
    실측(dealsitetv.com): 같은 도메인에서 6건 중 5건이 '원문 접속 실패'였는데
    1건은 성공했다 — 완전 차단이 아니라 간헐적이라는 뜻.
    2026-10: 로컬에서는 1초 안에 열리는 매체(더밸류뉴스·쿠키뉴스·딜사이트 등)가 Actions에서만
    4초 제한을 넘겨 실패해 요약이 비는 건이 최근 21일 반영 986건 중 25건이었다.
    그래서 제한을 10초로 늘리고 3회까지 시도한다(실패한 건만 지연되므로 전체 시간 영향은 작다).
    404·410은 삭제된 기사라 다시 해도 같으므로 바로 포기한다."""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                # 매체가 charset을 선언했으면(보안뉴스=EUC-KR) 그걸 우선한다.
                # 선언이 없을 때만 추정 — requests는 이 경우 ISO-8859-1로 잡아 한글이 깨진다.
                if "charset=" not in r.headers.get("content-type", "").lower():
                    r.encoding = r.apparent_encoding or r.encoding
                return r.text
            if r.status_code in (404, 410):
                return None
        except requests.RequestException:
            pass
        if attempt < 2:
            time.sleep(1.2 * (attempt + 1))
    return None


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    # 기자 이메일·저작권 꼬리 제거
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "", text)
    text = re.sub(r"(무단\s*전재|재배포\s*금지|저작권자).{0,40}$", "", text)
    return text.strip()


def _extract_naver(html: str) -> tuple[str | None, str | None]:
    soup = BeautifulSoup(html, "lxml")
    body = None
    for sel in NAVER_BODY_SELECTORS:
        node = soup.select_one(sel)
        if node:
            for junk in node.select("script, style, .end_photo_org, .img_desc, em.img_desc"):
                junk.decompose()
            body = _clean(node.get_text(" "))
            break
    press = None
    for sel in NAVER_PRESS_SELECTORS:
        node = soup.select_one(sel)
        if node and node.get("alt"):
            press = node["alt"].strip()
            break
    return body, press


_WORD = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _relates(title: str, text: str) -> bool:
    """본문 후보가 이 기사의 것인지 — 제목의 낱말이 하나라도 들어 있으면 참.
    조사가 붙은 낱말("JP모건이")은 끝 글자를 떼어 한 번 더 본다.
    날씨 위젯·다른 기사 소개문처럼 엉뚱한 덩어리를 걸러내는 최소한의 방어선이라 일부러 느슨하다."""
    for w in _WORD.findall(title or ""):
        if w in text or (len(w) >= 3 and w[:-1] in text):
            return True
    return False


def _candidates(html: str, soup):
    """본문 후보를 우선순위대로 하나씩 내준다(느리게 계산)."""
    for sel in GENERIC_BODY_SELECTORS:
        node = soup.select_one(sel)
        if node:
            for junk in node.select("script, style, iframe, .ad, .banner"):
                junk.decompose()
            yield _clean(node.get_text(" "))
    arts = soup.select(BARE_ARTICLE)
    if arts:
        texts = []
        for n in arts:
            for junk in n.select("script, style, iframe, .ad, .banner"):
                junk.decompose()
            texts.append(_clean(n.get_text(" ")))
        big = [t for t in texts if len(t) >= 200]
        # 소개문 카드가 여럿 섞인 페이지(뉴스웨이: 5개 중 본문은 1개)는 가장 긴 것이 기사다.
        # 큰 것이 하나뿐이면 본문이거나 페이지 전체 래퍼다 — 래퍼일 때는 '첫 <article>이 비어 있어
        # 건너뛰고 trafilatura로 가던' 기존 동작이 더 정확했다(이투데이). 그래서 이때는 첫 것만 본다.
        yield max(big, key=len) if len(big) >= 2 else texts[0]
    # 폴백 1: trafilatura — 셀렉터 목록에 없는 매체를 구조 분석으로 처리.
    #   <br> 문단·자체 div 레이아웃도 잡아낸다. p 밀도 방식보다 정확도가 높아 먼저 시도.
    if trafilatura is not None:
        try:
            got = trafilatura.extract(html, include_comments=False,
                                      include_tables=False, favor_recall=True)
            if got:
                yield _clean(got)
        except Exception:
            pass
    # 폴백 2: p 태그 밀도 방식
    yield _clean(" ".join(p.get_text(" ") for p in soup.find_all("p")))


def _extract_generic(html: str, title: str | None = None) -> str | None:
    """title을 주면 제목과 무관한 후보는 건너뛴다. 끝까지 없으면 None — 엉뚱한 본문으로
    요약을 만드느니 '추출 실패'로 두는 쪽이 낫다(실패는 화면에 드러나고, 오요약은 숨는다)."""
    soup = BeautifulSoup(html, "lxml")
    for text in _candidates(html, soup):
        if len(text) < 200:           # 본문이라 보기 어려운 짧은 덩어리 배제
            continue
        if title and not _relates(title, text):
            continue
        return text
    return None


def extract_many(articles: list, workers: int = 24, progress_every: int = 40) -> list:
    """본문 추출 병렬 처리 (10스레드). 같은 언론사 동시 요청은 드물어 안전."""
    done = [0]

    def work(a):
        r = extract(a, delay=0.0)
        done[0] += 1
        if done[0] % progress_every == 0:
            print(f"  본문 추출 {done[0]}/{len(articles)}")
        return r

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, articles))
    return articles


def extract(article: dict, delay: float = 0.3) -> dict:
    """기사 dict에 body/press/extract_ok/extract_fail_reason 채워 반환."""
    body, press, reason = None, None, None
    naver_url = article.get("naver_url") or ""
    original_url = article.get("original_url") or ""

    # 1순위: 네이버 뉴스
    if "news.naver.com" in naver_url:
        html = _get(naver_url)
        if html:
            body, press = _extract_naver(html)
        if not body:
            reason = "네이버 본문 셀렉터 매칭 실패"

    # 2순위: 원문 (네이버 링크가 원문 URL인 경우 포함)
    if not body:
        target = original_url or naver_url
        if target:
            html = _get(target)
            if html:
                body = _extract_generic(html, article.get("title"))
                if not body:
                    reason = (reason or "") + " / 원문 추출 실패"
            else:
                reason = (reason or "") + " / 원문 접속 실패"

    if delay:
        time.sleep(delay)
    article["body"] = body
    if press:
        article["press"] = press
    article["extract_ok"] = 1 if body else 0
    article["extract_fail_reason"] = None if body else (reason or "알 수 없음").strip(" /")
    return article
