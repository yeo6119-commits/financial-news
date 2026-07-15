# =============================================================
# summarizer.py — Groq 요약 (v2.5)
# 문체 프롬프트 재작성: 어미 라벨 오출력("~입니다 -함") 방지
# 절대 규칙: 기사 1건 = 호출 1회. 배치 금지. 실패해도 기사는 보존.
# =============================================================
import os
import time
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

PROMPT = """아래 기사를 읽고 핵심을 2~3줄로 요약하라. 실무 보고용 개조식으로 쓴다.

[형식]
- 각 줄은 "- " 로 시작. 2줄 또는 3줄. 그 외 텍스트는 출력 금지.
- 첫 줄은 "회사명, 핵심 내용" 형태로 무슨 일인지 한눈에 보이게 쓴다.
- 협력사·제휴사가 있으면 첫 줄 끝에 (w/회사명) 으로 표기한다.

[문체 — 개조식 명사형 종결]
모든 줄은 서술어 없이 명사(구)로 끝낸다.
  "출범했다" → "출범"          "도입한다" → "도입"
  "제공할 계획이다" → "제공 예정"   "구성돼 있다" → "구성"
  "추진하고 있다" → "추진 중"      "지원한다" → "지원"
  "~하는 프로그램이다" → "~하는 프로그램"
금지: -입니다, -습니다, -한다, -했다, -이다, -됨, -함, -임

[내용]
- 본문에 있는 사실만 쓴다. 해석·평가·전망을 지어내지 말 것.
- 수치·기간·기능명 등 구체적 사실을 우선 담는다.
- 줄마다 역할을 정하지 말고, 핵심 사실을 고르게 나눠 담는다.
- 약어는 처음 나올 때 괄호로 풀어쓴다. 예: AI(인공지능)

[예시]
- KB금융, 실전형 AI(인공지능) 인재 양성 프로그램 'KB AI Lab' 출범
- 그룹 AI 교육체계인 KB AI 아카데미 최고 과정 수료 직원 대상의 프로젝트형 인재 육성 프로그램
- 현업 과제 발굴 및 AI 서비스 직접 구현, 2주간 심화 교육과 10주간 실전 프로젝트로 구성

기사 제목: {title}
기사 본문:
{body}"""


# 개조식 위반 — 서술형 어미로 끝나면 거부
BAD_ENDINGS = ("입니다", "습니다", "됩니다", "합니다", "이다", "한다", "했다",
               "된다", "있다", "예정이다", "것이다", "말했다", "밝혔다",
               "-함", "-임", "하였다", "된 바 있다")


def _validate(text: str, cfg: dict) -> str | None:
    v = cfg["summarizer"]["validation"]
    bullet = v.get("each_starts_with", "-")
    lo = v.get("min_lines", 2)
    hi = v.get("max_lines", 3)
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    # 모델이 * 로 시작하는 습관이 남아 있으면 - 로 정규화
    lines = [("- " + l.lstrip("*-• ").strip()) if l[:1] in "*-•" else l for l in lines]
    if not (lo <= len(lines) <= hi):
        return None
    for l in lines:
        if not l.startswith(bullet):
            return None
        if len(l) < v["min_line_chars"]:
            return None
        body = l.lstrip("- ").strip().rstrip(".")
        if any(body.endswith(e) for e in BAD_ENDINGS):
            return None
    return "\n".join(lines)


def summarize(article: dict, cfg: dict) -> dict:
    """summary / summary_ok / summary_fail_reason 채워 반환."""
    if not article.get("body"):
        article["summary_ok"] = 0
        article["summary_fail_reason"] = "본문 없음"
        return article

    s = cfg["summarizer"]
    assert s["batch"] is False, "배치 요약은 금지됨 (v2.3 스펙)"

    body = article["body"][:3000]           # 1건 기준 충분·안전한 길이
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
               "Content-Type": "application/json"}
    prompt = PROMPT.format(title=article["title"], body=body)

    # 모델 폴백 체인: 주 모델(70b) → 대체 모델(8b)
    # 두 모델은 일일 토큰 쿼터가 별개이므로, 70b 한도 소진 시 8b가 이어받는다.
    models = [s["model"]]
    fb = s.get("fallback_model")
    if fb and fb != s["model"]:
        models.append(fb)

    last_err = None
    for mi, model in enumerate(models):
        payload = {"model": model, "max_tokens": 300, "temperature": 0.2,
                   "messages": [{"role": "user", "content": prompt}]}
        quota_out = False
        for attempt in range(s["max_retries"]):
            try:
                r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
                if r.status_code == 429:
                    msg = ""
                    try:
                        msg = r.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    # 일일 한도(TPD) 소진이면 재시도 무의미 → 즉시 다음 모델로
                    if "per day" in msg or "TPD" in msg:
                        last_err = f"레이트리밋(일일한도:{model})"
                        quota_out = True
                        break
                    # 분당 한도(TPM)는 잠시 기다리면 회복
                    time.sleep(s["backoff_base_seconds"] * (2 ** attempt))
                    last_err = "레이트리밋"
                    continue
                r.raise_for_status()
                raw = r.json()["choices"][0]["message"]["content"]
                valid = _validate(raw, cfg)
                if valid:
                    article["summary"] = valid
                    article["summary_ok"] = 1
                    article["summary_fail_reason"] = None
                    article["summary_model"] = model
                    time.sleep(0.5)
                    return article
                last_err = "형식 검증 실패(3줄/별표/길이)"
            except Exception as e:
                last_err = str(e)[:100]
            time.sleep(s["backoff_base_seconds"] * (attempt + 1))
        if quota_out and mi + 1 < len(models):
            continue                        # 다음 모델로 폴백
        if not quota_out:
            break                           # 쿼터 문제가 아니면 폴백해도 같은 결과

    article["summary_ok"] = 0
    article["summary_fail_reason"] = last_err or "알 수 없음"
    return article
