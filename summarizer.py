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

PROMPT = """기사를 3~4줄 개조식으로 요약. 각 줄 "- "로 시작. 그 외 텍스트 출력 금지.

[줄 수] 3~4줄. 본문에 사실이 적으면 3줄, 많으면 4줄. 2줄 이하로 줄이지 말 것.

[밀도] 각 줄 25~70자. 단어 나열 금지. 무엇이 어떻게 작동하는지 알 수 있게 쓴다.
  나쁨: - 은행 자금 주식매매 연동
  좋음: - 은행 계좌 자금을 증권 계좌로 옮기지 않고 주식 매매에 바로 사용하는 구조

[문체] 모든 줄을 명사(구)로 끝낸다.
  "출범했다"→"출범"  "제공할 계획이다"→"제공 예정"  "추진하고 있다"→"추진 중"
  금지어미: -입니다 -습니다 -한다 -했다 -이다 -된다 -됨 -함 -임

[내용] 첫 줄은 "회사명, 핵심내용". 협력사는 (w/회사명).
  본문의 수치·명칭·기능·작동방식을 그대로 담는다.
  부가정보는 괄호로: (연말 구축 목표), (7.3~4일), (혁금 지정)
  대상·주체별로 나뉘는 내용은 (소관부서), (임원) 처럼 앞에 표기 가능.
  본문에 없는 해석·평가·비판은 절대 쓰지 말 것. (예: "이자 장사 비판 탈출" 같은 표현 금지)
  약어는 AI(인공지능)처럼 처음 한 번 풀어쓴다.

[예시] 형식과 밀도만 참고. 내용을 그대로 쓰지 말 것. 반드시 아래 본문만 요약.
- NH농협은행, AI(인공지능) 웰니스 솔루션 'HEALLO' 서울지역 100여 개 지점 도입(w/쿠도커뮤니케이션)
- 카메라 기반 AI 영상 분석으로 얼굴을 읽어 생체 신호 기반 건강지표를 참고 정보로 제공하는 비접촉 방식
- 지점 키오스크에서 약 30초간 측정 후 QR코드로 모바일 앱에 결과 전달, 날짜별 이력으로 컨디션 관리 지원

제목: {title}
본문:
{body}"""


# 개조식 위반 — 서술형 어미로 끝나면 거부
BAD_ENDINGS = ("입니다", "습니다", "됩니다", "합니다", "이다", "한다", "했다",
               "된다", "있다", "예정이다", "것이다", "말했다", "밝혔다",
               "-함", "-임", "하였다", "된 바 있다")


# 서술형 어미 → 명사(구) 기계 보정.
#   인터뷰·해설 기사에서 모델이 자연스럽게 서술체를 쓰는 바람에 형식 검증에서
#   통째로 버려지는 건이 많았다. temperature=0이라 재시도해도 같은 출력이 나오므로
#   LLM을 다시 부르지 않고 어미만 바로잡는다 (추가 토큰 0).
#   목표 문체는 프롬프트와 동일: "출범했다"→"출범", "제공할 계획이다"→"제공 예정",
#   "추진하고 있다"→"추진 중". '-함/-임'은 프롬프트에서 금지어미이므로 쓰지 않는다.
_ENDING_FIXES = [
    # 인용 꼬리표부터 떼어낸다 ("…라고 밝혔다")
    (re.compile(r"(?:라)?고\s*(?:밝혔다|말했다|전했다|설명했다|강조했다|덧붙였다)$"), ""),
    (re.compile(r"(?:밝혔다|말했다|전했다|설명했다|강조했다|덧붙였다)$"), ""),
    # 진행 → '중'
    (re.compile(r"로\s*하고\s*있다$"), ""),      # "…을 목표로 하고 있다" → "…을 목표"
    (re.compile(r"하고\s*있다$"), " 중"),
    (re.compile(r"하는\s*중이다$"), " 중"),
    (re.compile(r"되고\s*있다$"), " 중"),
    # 의지 표현 → 명사구 ("선보이겠다"→"선보이겠다는 계획")
    (re.compile(r"겠다$"), "겠다는 계획"),
    # 예정·계획 → '예정'
    (re.compile(r"(?:할|하기로)\s*(?:계획|예정|방침)이다$"), " 예정"),
    (re.compile(r"(?:계획|예정|방침)이다$"), " 예정"),
    (re.compile(r"기로\s*했다$"), " 예정"),
    (re.compile(r"할\s*전망이다$"), " 전망"),
    (re.compile(r"것이다$"), " 전망"),
    # 가능
    (re.compile(r"할\s*수\s*있다$"), " 가능"),
    (re.compile(r"수\s*있다$"), " 가능"),
    # 일반 서술 어미 제거 → 명사로 끝맺음
    (re.compile(r"(?:했|하였|하겠|한|합)다$"), ""),
    (re.compile(r"했습니다$|합니다$|입니다$|습니다$"), ""),
    (re.compile(r"(?:됐|되었|되|된)다$"), ""),
    (re.compile(r"됩니다$"), ""),
    (re.compile(r"이다$"), ""),
    (re.compile(r"된\s*바\s*있다$"), ""),
]
# 보정 후 남으면 안 되는 잔여 조사 (어미를 떼면서 '를/을/이/가'로 끝나는 경우)
_DANGLING = re.compile(r"[을를이가은는와과에의로]$")


def fix_ending(line: str) -> str:
    """한 줄의 서술형 어미를 명사(구)로 바로잡는다."""
    s = line.strip().rstrip(".")
    for _ in range(3):                      # "…할 계획이라고 밝혔다" 처럼 겹친 꼬리 처리
        before = s
        for rx, rep in _ENDING_FIXES:
            s2 = rx.sub(rep, s)
            if s2 != s:
                s = s2.strip()
                break
        if s == before:
            break
    s = _DANGLING.sub("", s).strip()
    s = re.sub(r"\s{2,}", " ", s)
    return s


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
    # 줄 수 초과는 버리지 말고 앞에서 자른다 — 한국 기사는 역피라미드라 앞줄이 핵심
    if len(lines) > hi:
        lines = lines[:hi]
    if len(lines) < lo:
        return None                      # 부족한 줄은 기계적으로 만들 수 없음
    out = []
    for l in lines:
        if not l.startswith(bullet):
            return None
        body = fix_ending(l.lstrip("- ").strip())   # 서술형 → 명사구 보정
        if any(body.endswith(e) for e in BAD_ENDINGS):
            return None                  # 보정으로도 못 고친 어미
        line = f"{bullet} {body}"
        if len(line) < v["min_line_chars"]:
            return None
        out.append(line)
    return "\n".join(out)


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
        rate_hits = 0
        # 분당 한도는 잠깐 기다리면 풀리므로, 형식 재시도(max_retries)와 별개로
        # 429에는 좀 더 여유를 준다.
        for attempt in range(s["max_retries"] + 4):
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
                    # 분당 한도(TPM)는 잠시 기다리면 회복.
                    #   Groq가 알려주는 재시도 대기시간(retry-after)을 우선 존중한다.
                    wait = r.headers.get("retry-after")
                    try:
                        wait = float(wait) if wait else s["backoff_base_seconds"] * (2 ** attempt)
                    except (TypeError, ValueError):
                        wait = s["backoff_base_seconds"] * (2 ** attempt)
                    wait = min(wait, 30)          # 과도한 대기 방지
                    time.sleep(wait)
                    last_err = "분당한도"
                    rate_hits += 1
                    if rate_hits >= 6:           # 6회 기다려도 안 풀리면 포기
                        break
                    continue
                r.raise_for_status()
                data = r.json()
                used = (data.get("usage") or {}).get("total_tokens", 0)
                if used:
                    TOKEN_USAGE[model] = TOKEN_USAGE.get(model, 0) + used
                raw = data["choices"][0]["message"]["content"]
                v = cfg["summarizer"]["validation"]
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
                last_err = "형식 검증 실패(%d~%d줄/불릿/25자/어미)" % (
                    v.get("min_lines", 2), v.get("max_lines", 4))
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
