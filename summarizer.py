# =============================================================
# summarizer.py — Groq 요약 (v2.5)
# 문체 프롬프트 재작성: 어미 라벨 오출력("~입니다 -함") 방지
# 절대 규칙: 기사 1건 = 호출 1회. 배치 금지. 실패해도 기사는 보존.
# =============================================================
import os
import re
import time

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# 모델별 누적 토큰 사용량 (Groq 응답의 usage 필드 — 추정 아닌 실측)
TOKEN_USAGE: dict[str, int] = {}
DAILY_LIMIT = 100_000        # Groq 무료 티어 모델별 일일 토큰 한도(TPD)

PROMPT = """기사를 2~3줄 개조식으로 요약. 각 줄 "- "로 시작. 그 외 텍스트 출력 금지.

문체: 모든 줄을 명사(구)로 끝낸다.
 "출범했다"→"출범"  "제공할 계획이다"→"제공 예정"  "추진하고 있다"→"추진 중"
 금지어미: -입니다 -습니다 -한다 -했다 -이다 -된다 -됨 -함 -임

내용: 첫 줄은 "회사명, 핵심내용". 협력사는 (w/회사명). 본문 사실만 쓰고 지어내지 말 것.
수치·기간·기능명 우선. 약어는 AI(인공지능)처럼 풀어쓴다.

예:
- KB금융, 실전형 AI(인공지능) 인재 양성 프로그램 'KB AI Lab' 출범
- KB AI 아카데미 최고 과정 수료 직원 대상 프로젝트형 육성 프로그램
- 2주 심화 교육과 10주 실전 프로젝트로 구성

제목: {title}
본문:
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


# 요약에 불필요한 상용구 — 토큰만 먹고 내용이 없음
_BOILER = [
    re.compile(r"^\[[^\]]{0,30}(기자|특파원|뉴스|일보|경제|투데이)[^\]]{0,20}\]\s*"),  # [OO뉴스 김OO 기자]
    re.compile(r"[\w.\-]+@[\w.\-]+\.\w+"),                       # 이메일
    re.compile(r"(사진|자료|그래픽|이미지)\s*[=:／/][^\n]{0,40}"),      # 사진=OO / 자료=OO
    re.compile(r"저작권자.{0,60}"),
    re.compile(r"무단\s?전재.{0,40}"),
    re.compile(r"재배포\s?금지.{0,20}"),
    re.compile(r"※[^\n]{0,60}"),
    re.compile(r"▶[^\n]{0,60}"),
    re.compile(r"관련기사[^\n]{0,60}"),
    re.compile(r"\bCopyright\b[^\n]{0,60}", re.I),
]


def compact_body(text: str, limit: int) -> str:
    """상용구·중복 공백을 걷어내고 limit자로 자른다.
    같은 limit이라도 실질 내용이 더 많이 담기므로 토큰 대비 정보량이 오른다."""
    t = text or ""
    for rx in _BOILER:
        t = rx.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def summarize(article: dict, cfg: dict) -> dict:
    """summary / summary_ok / summary_fail_reason 채워 반환."""
    if not article.get("body"):
        article["summary_ok"] = 0
        article["summary_fail_reason"] = "본문 없음"
        return article

    s = cfg["summarizer"]
    assert s["batch"] is False, "배치 요약은 금지됨 (v2.3 스펙)"

    body = compact_body(article["body"], s.get("body_chars", 1500))
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
        payload = {"model": model, "max_tokens": s.get("max_tokens", 200), "temperature": 0.2,
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
                data = r.json()
                used = (data.get("usage") or {}).get("total_tokens", 0)
                if used:
                    TOKEN_USAGE[model] = TOKEN_USAGE.get(model, 0) + used
                raw = data["choices"][0]["message"]["content"]
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


def usage_report() -> str:
    """모델별 토큰 사용량 — 일일 한도 대비 잔량 표시"""
    if not TOKEN_USAGE:
        return ""
    parts = []
    for model, used in TOKEN_USAGE.items():
        m = re.search(r"(\d+b)", model)
        short = m.group(1) if m else model
        pct = used * 100 // DAILY_LIMIT
        parts.append(f"{short} {used:,}/{DAILY_LIMIT:,} ({pct}%)")
    return " · ".join(parts)
