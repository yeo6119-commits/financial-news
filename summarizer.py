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

예시 (형식만 참고. 아래 내용을 그대로 쓰지 말 것. 반드시 주어진 본문만 요약):
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


def _grounded(summary: str, title: str, body: str) -> bool:
    """요약이 원문에 근거하는지 검증.

    모델이 요약할 내용을 못 찾으면 프롬프트의 예시를 그대로 복창하거나
    없는 내용을 지어낸다. 요약의 명사 토큰이 원문에 얼마나 등장하는지로 걸러낸다.
    (한국 기사 요약은 대부분 추출적이라 정상 요약은 겹침이 높다)
    """
    src = (title + " " + body).lower()
    toks = re.findall(r"[가-힣]{2,}|[A-Za-z]{2,}", summary)
    toks = [t for t in toks if len(t) >= 2]
    if not toks:
        return False
    hits = sum(1 for t in toks if t.lower() in src)
    return hits / len(toks) >= 0.55


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
    """상용구를 걷어내고 '문장 단위'로 limit자까지만 담는다.

    - 한국 기사는 역피라미드라 앞 문장에 5W1H가 다 있다.
    - 문장 중간에서 자르면 모델이 끊긴 문장을 해석하느라 오히려 품질이 떨어지고
      토큰도 낭비된다. 문장 경계로 자르면 같은 토큰에 완결된 정보가 담긴다.
    """
    t = text or ""
    for rx in _BOILER:
        t = rx.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) <= limit:
        return t
    # 문장 경계로 분할 후 limit 안에서 최대한 담기
    sents = re.split(r"(?<=[.!?다])\s+", t)
    out = []
    total = 0
    for sn in sents:
        if total + len(sn) > limit:
            break
        out.append(sn)
        total += len(sn) + 1
    return " ".join(out) if out else t[:limit]


def summarize(article: dict, cfg: dict) -> dict:
    """summary / summary_ok / summary_fail_reason 채워 반환."""
    if not article.get("body"):
        article["summary_ok"] = 0
        article["summary_fail_reason"] = "본문 없음"
        return article

    s = cfg["summarizer"]
    assert s["batch"] is False, "배치 요약은 금지됨 (v2.3 스펙)"

    body = compact_body(article["body"], s.get("body_chars", 1100))
    # 본문이 지나치게 짧으면 요약해도 환각이 나온다 (예시 복창의 원인).
    # 호출 자체를 생략해 토큰을 아끼고, 실패 사유를 남긴다.
    if len(body) < s.get("min_body_chars", 200):
        article["summary_ok"] = 0
        article["summary_fail_reason"] = "본문 부족(%d자)" % len(body)
        return article
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
        payload = {"model": model, "max_tokens": s.get("max_tokens", 180),
                   "temperature": 0,          # 결정적 출력 → 형식 오류·재시도 감소
                   "messages": [{"role": "user", "content": prompt}]}
        quota_out = False
        fmt_fail = 0
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
                if valid and not _grounded(valid, article["title"], body):
                    # 예시 복창·환각 — 재시도해도 같은 결과이므로 즉시 실패 처리
                    last_err = "환각(원문 근거 없음)"
                    valid = None
                    break
                if valid:
                    article["summary"] = valid
                    article["summary_ok"] = 1
                    article["summary_fail_reason"] = None
                    article["summary_model"] = model
                    time.sleep(0.5)
                    return article
                # 형식 실패는 같은 프롬프트로 재호출해도 대개 같은 결과 → 1회만 재시도.
                # (3회 재시도 시 1건에 정상 3건치 토큰을 태우게 됨)
                last_err = "형식 검증 실패(2~3줄/불릿/어미)"
                fmt_fail += 1
                if fmt_fail >= 2:
                    break
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
