"""검토 에이전트 — 필터를 통과한 기사가 '진짜' 금융사의 디지털·AI 사안인지
   LLM으로 재검한다. 규칙(HARD_EXCLUDE 등)이 놓친 오탐을 걸러내는 최종 관문.

파이프라인에서 classify 다음, summarize 앞에 위치한다.
  · 규칙 필터: 명시적 키워드로 거른다 (빠르지만 새 표현은 놓침)
  · 검토 에이전트: 문맥을 읽어 판단한다 (느리지만 놓친 것도 잡음)

무관 판정 시 article["excluded"]=1 로 표시하고 사유를 남긴다.
요약(Groq 호출)을 어차피 하므로, 그 앞에서 거르면 무관 기사의 요약 비용도 아낀다.
"""
import os
import time
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# 판정 기준 — 프롬프트에 그대로 들어간다.
SYSTEM = """너는 한국 금융 뉴스 분류기다. 기사가 '금융회사의 디지털·AI 관련 활동'인지 판정한다.

관련 있음(YES)의 예:
- AI·인공지능 도입/개발/적용 (신용평가, 상담, 챗봇, 리스크관리 등)
- 디지털 서비스·앱·플랫폼 출시/개편/고도화
- 데이터·클라우드·API·마이데이터·오픈뱅킹
- 핀테크·블록체인·디지털자산·간편결제(디지털 맥락)
- 디지털 전환(DX/AX) 전략·조직·투자

관련 없음(NO)의 예:
- 혜택·이벤트·캠페인·포인트·경품 (앱에서 하더라도 마케팅임)
- 금융상품 (펀드·신탁·특판·RP·ELS·예적금·대출상품)
- 실적·순위·수상·브랜드평판
- 인사·사외이사·조직개편·부고
- 오프라인 점포·지점·PB센터 개설
- 교육·연수·아카데미·프로그램·세미나·전시
- 봉사·기부·CSR·후원
- 규제·감독·제재·소송·국정감사 (제도 이슈)
- 단순 대출 확대·해외 사업·투자 유치

제목에 'AI'나 '디지털'이라는 단어가 있어도, 그것이 기사의 '핵심 주제'가 아니라
부수적 언급이면 NO다. (예: 교육 프로그램에 'AI 강의'가 포함된 경우 → NO)

반드시 YES 또는 NO 한 단어만 답하라."""


def review(article: dict, cfg: dict) -> dict:
    """기사 1건을 검토. 무관하면 excluded=1 표시."""
    rc = cfg.get("reviewer", {})
    if not rc.get("enabled", False):
        return article
    if article.get("excluded"):          # 이미 앞 단계에서 제외됨
        return article

    title = article.get("title", "")
    body = article.get("body") or ""
    lead = body[:500]                    # 본문 앞부분만
    user = f"제목: {title}\n본문: {lead}\n\n이 기사는 금융사의 디지털·AI 활동인가? YES/NO:"

    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
               "Content-Type": "application/json"}
    payload = {
        "model": rc.get("model", "llama-3.1-8b-instant"),
        "max_tokens": 3,                 # YES/NO만 — 토큰 최소
        "temperature": 0,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
    }

    for attempt in range(rc.get("max_retries", 2)):
        try:
            r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=20)
            if r.status_code == 200:
                ans = r.json()["choices"][0]["message"]["content"].strip().upper()
                if ans.startswith("NO"):
                    article["excluded"] = 1
                    article["exclude_reason"] = "검토 에이전트: 디지털·AI 무관 판정"
                    article["reviewed"] = "NO"
                else:
                    article["reviewed"] = "YES"
                return article
            if r.status_code == 429:      # 레이트리밋 — 잠시 대기
                wait = r.headers.get("retry-after")
                time.sleep(min(float(wait) if wait else 2 ** attempt, 20))
                continue
            # 그 외 오류: 판정 보류(통과시킴). 검토 실패로 기사를 잃지 않는다.
            article["reviewed"] = f"보류({r.status_code})"
            return article
        except Exception as e:
            article["reviewed"] = f"보류({str(e)[:20]})"
            return article
    article["reviewed"] = "보류(재시도 초과)"
    return article


def review_many(articles: list, cfg: dict, progress_every: int = 20) -> None:
    """반영 대상 기사들을 순회 검토. 무관 판정된 것은 excluded=1 이 된다."""
    rc = cfg.get("reviewer", {})
    if not rc.get("enabled", False):
        return
    targets = [a for a in articles if not a.get("excluded")]
    reviewed_no = 0
    for i, a in enumerate(targets, 1):
        review(a, cfg)
        if a.get("reviewed") == "NO":
            reviewed_no += 1
        if i % progress_every == 0:
            print(f"  검토 {i}/{len(targets)} (무관 {reviewed_no}건 제외)")
    if targets:
        print(f"  검토 완료: {len(targets)}건 중 {reviewed_no}건 무관 제외")
