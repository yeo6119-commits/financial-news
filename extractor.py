# =============================================================
# extractor.py — 기사 본문 추출 (v2.3)
# 우선순위: 네이버 뉴스 링크 → originallink → 실패 보존
# =============================================================
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# 네이버 뉴스 본문 셀렉터 (일반 / 연예 / 스포츠 구버전)
NAVER_BODY_SELECTORS = ["#dic_area", "#articeBody", "#newsEndContents", "#articleBodyContents"]
NAVER_PRESS_SELECTORS = [".media_end_head_top_logo img", ".press_logo img"]
# 일반 언론사 사이트 본문 후보 (originallink 폴백용)
GENERIC_BODY_SELECTORS = [
    "article", "#article-view-content-div", ".article_body", ".news_body",
    "#articleBody", ".article-view", "#news_body_area", ".view_con", "#CmAdContent",
]


def _get(url: str, timeout: int = 4) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or r.encoding
            return r.text
    except requests.RequestException:
        pass
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


def _extract_generic(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for sel in GENERIC_BODY_SELECTORS:
        node = soup.select_one(sel)
        if node:
            for junk in node.select("script, style, iframe, .ad, .banner"):
                junk.decompose()
            text = _clean(node.get_text(" "))
            if len(text) >= 200:      # 본문이라 보기 어려운 짧은 덩어리 배제
                return text
    # 최후: p 태그 밀도 방식
    paras = [p.get_text(" ") for p in soup.find_all("p")]
    text = _clean(" ".join(paras))
    return text if len(text) >= 200 else None


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
                body = _extract_generic(html)
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
