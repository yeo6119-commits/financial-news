# =============================================================
# summarizer.py — Groq 요약 (v2.5)
# 문체 프롬프트 재작성: 어미 라벨 오출력("~입니다 -함") 방지
# 절대 규칙: 기사 1건 = 호출 1회. 배치 금지. 실패해도 기사는 보존.
# =============================================================
import os
import time
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

PROMPT = """당신은 금융지주 임원 보고서를 쓰는 애널리스트다. 아래 기사를 정확히 3줄로 요약하라.

[문체 규칙 — 가장 중요]
모든 문장은 종결어미 없이 명사형 또는 -함/-임체로 끝낸다.
"~입니다", "~한다", "~했다" 같은 서술형 어미를 쓰지 말고, 아래처럼 변환하라.

  나쁜 예 → 좋은 예
  "서비스를 제공할 계획입니다" → "서비스를 제공할 계획임"
  "지원을 확대할 것입니다" → "지원을 확대할 방침임"
  "도입했다" → "도입함"
  "출시한다" → "출시함"
  "받을 수 있는 구조입니다" → "받을 수 있는 구조임"
  "강화하고 있다" → "강화 중임"
  "분석된다" → "분석됨"
  "높였다" → "높임"

절대 금지: 문장 끝에 "-함", "-임", "-할 계획" 같은 표시를 별도로 덧붙이지 말 것.
어미 자체를 바꿔 쓰는 것이지, 라벨을 붙이는 게 아니다.

[내용 규칙 — 모든 유형의 기사에 적용]
1줄: 무슨 일이 있었는지 (주체와 핵심 사실)
2줄: 구체적인 내용 (기능·수치·방식·쟁점 등 기사의 알맹이)
3줄: 의미·전망 (향후 계획, 기대 효과, 시장·경쟁상 함의 중 기사에 있는 것)

기사 유형에 따라 3줄의 성격은 달라진다. 억지로 하나의 틀에 맞추지 말 것.
  · 서비스 출시: 무엇을 도입 → 어떻게 달라짐 → 향후 계획
  · 비교·분석: 무엇이 쟁점 → 각 진영의 강점·약점 → 전망과 시사점
  · 전략·인터뷰: 누가 무엇을 제시 → 핵심 논거 → 실행 방향
  · 실적·투자: 얼마를 어디에 → 배경과 구성 → 기대 효과
  · 협약·제휴: 누구와 무엇을 → 협력 내용 → 확대 계획
  · 여러 소식이 묶인 기사: 가장 비중이 큰 소식 하나를 골라 3줄로 정리

3줄에 담을 내용이 부족해도 반드시 3줄을 채운다.
기사에 향후 계획이 없으면 3줄째에 사실의 의미나 배경을 쓴다.

[형식 규칙]
- 각 줄은 반드시 * 로 시작하는 한 문장
- 정확히 3줄. 그 외 어떤 텍스트(인사말, 설명, 제목)도 출력 금지
- 본문에 없는 내용을 추정하거나 지어내지 말 것
- 약어는 처음 등장 시 괄호로 풀어씀. 예: AI(인공지능), MTS(모바일트레이딩시스템), FDS(이상금융거래탐지시스템)

[올바른 출력 예시]
* KB국민은행이 포스코와 협약을 맺고 철강 공급망 기업 대상 맞춤형 금융 서비스를 도입함
* My POSCO 플랫폼 고객은 자금 조달과 함께 인력 채용·경영 관리·복지 비용 절감을 한 번에 지원받게 됨
* 금융·비금융 통합 솔루션으로 공급망 생태계 전반의 상생 지원을 확대할 계획임

기사 제목: {title}
기사 본문:
{body}"""


# 문장 끝에 라벨처럼 붙는 오출력 (8b 모델 흔한 실수)
BAD_TAILS = ("-함", "-임", "-할 계획", "- 함", "- 임", "(-함)", "(-임)")
# 서술형 어미 (보고체 위반)
BAD_ENDINGS = ("입니다", "습니다", "됩니다", "합니다", "이다", "한다", "했다",
               "된다", "있다", "예정이다", "것이다", "말했다", "밝혔다")


def _validate(text: str, cfg: dict) -> str | None:
    v = cfg["summarizer"]["validation"]
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) != v["exact_lines"]:
        return None
    for l in lines:
        if not l.startswith(v["each_starts_with"]):
            return None
        if len(l) < v["min_line_chars"]:
            return None
        body = l.lstrip("* ").strip().rstrip(".")
        # 라벨 오출력 거부
        if any(body.endswith(t) for t in BAD_TAILS):
            return None
        # 서술형 어미 거부
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

    body = article["body"][:6000]           # 1건 기준 충분·안전한 길이
    payload = {
        "model": s["model"],
        "max_tokens": 500,
        "temperature": 0.2,
        "messages": [{"role": "user",
                      "content": PROMPT.format(title=article["title"], body=body)}],
    }
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
               "Content-Type": "application/json"}

    last_err = None
    for attempt in range(s["max_retries"]):
        try:
            r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
            if r.status_code == 429:         # 레이트리밋 — 지수 백오프
                wait = s["backoff_base_seconds"] * (2 ** attempt)
                time.sleep(wait)
                last_err = "레이트리밋"
                continue
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            valid = _validate(raw, cfg)
            if valid:
                article["summary"] = valid
                article["summary_ok"] = 1
                article["summary_fail_reason"] = None
                time.sleep(0.6)              # 무료 티어 예의상 간격
                return article
            last_err = "형식 검증 실패(3줄/별표/길이)"
        except Exception as e:
            last_err = str(e)[:100]
        time.sleep(s["backoff_base_seconds"] * (attempt + 1))

    article["summary_ok"] = 0
    article["summary_fail_reason"] = last_err or "알 수 없음"
    return article
