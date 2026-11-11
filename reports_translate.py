# =============================================================
# reports_translate.py — 해외(영문) 보고서의 제목·설명을 한국어로 번역
#
# reports.py가 모은 항목 중 제목에 한글이 없는 것(BIS·ECB·연준·IMF·맥킨지 등과 그 발간 소식 기사)만 번역한다.
#   · 구독 Claude(claude -p, CLAUDE_CODE_OAUTH_TOKEN)만 쓴다 — 해외 영문 트랙(foreign.py)과 같은 경로이고, Groq·API 키를 쓰지 않는다.
#   · 항목 1건 = 호출 1회(제목+설명). 여러 건을 묶지 않는다 — 묶으면 모델이 일부를 조용히 빠뜨린다(요약 배치 금지와 같은 이유).
#   · 번역은 원문을 바꾸지 않는다: 원제·원문 설명은 그대로 두고 title_ko·desc_ko를 따로 저장한다. 화면에는 원제를 같이 보여 준다.
#   · 검증: 한글이 있어야 하고, 번역문에 남은 영문 단어는 원문에 있던 것이어야 하며(지어낸 고유명사 차단),
#     큰 수치는 원문에 있던 숫자여야 한다. 통과 못 하면 번역을 붙이지 않고 영문 그대로 보여 준다(항목당 최대 2번 시도).
#   · 구독 Claude가 없거나(Actions에 토큰 없음) 한도가 소진되면 번역만 건너뛴다 — 수집·페이지 생성은 그대로 된다.
# =============================================================
import re
import time

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9&.'-]*")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_REFUSE = re.compile(r"죄송|번역할 수|제공해 주|알려 주|확인해 주|주어진 (?:제목|설명|내용)")
MAX_TRIES = 2

PROMPT = """다음은 해외 기관·매체가 공개한 보고서(또는 보고서 발간 소식)의 제목과 설명입니다. 한국어로 번역하세요.
- 제목: 자연스러운 한국어 한 줄로 옮깁니다. 기관·회사·제품명은 한국에서 쓰는 표기(맥킨지, 골드만삭스, 국제통화기금 등)로 쓰고, 확실하지 않으면 영문 그대로 둡니다. 관용구는 직역하지 말고 뜻으로 옮깁니다.
- 설명: 원문에 있는 내용만 옮깁니다. 요약하거나 줄이지 말고, 해석·전망·평가를 덧붙이지 않습니다. 원문 설명이 비어 있으면 '(없음)'이라고 씁니다.
- 원문에 없는 영문 약어·영문 표기를 새로 덧붙이지 않습니다(예: central counterparties → 중앙청산소, 괄호에 약어를 붙이지 않음).
- 수치·날짜·퍼센트는 원문 그대로 옮깁니다(예: $1.1 trillion → 1.1조 달러, 60-70 percent → 60~70%).
- 아래 두 줄 형식 그대로만 출력하고 다른 말은 쓰지 않습니다.
제목: <번역한 제목>
설명: <번역한 설명>

원문 제목: {title}
원문 설명: {desc}
"""


def needs_translation(it: dict) -> bool:
    """제목에 한글이 없으면 외국어(영문) 항목이다."""
    return bool(it.get("title")) and not _HANGUL.search(it["title"])


def _sig(n: str) -> str:
    """숫자의 유효숫자 — 단위 환산(250 billion → 2,500억)을 같은 수로 본다."""
    return re.sub(r"[.,]", "", n).strip("0")


def _numbers_ok(ko: str, src: str) -> bool:
    have = {_sig(n) for n in _NUM.findall(src)}
    for n in _NUM.findall(ko):
        plain = re.sub(r",", "", n)
        if "." not in plain and int(plain.split(".")[0] or 0) <= 31:      # 날짜·월·작은 개수는 환산·표기가 달라 검사하지 않는다
            continue
        if _sig(n) not in have:
            return False
    return True


def _latin_ok(ko: str, src: str) -> bool:
    low = src.lower()
    return all(len(t) < 2 or t.lower().strip(".'-") in low for t in _LATIN.findall(ko))


def valid_desc_ko(ko: str, en: str, title_en: str = "") -> str:
    """번역 설명 검증. 통과하면 정리한 문자열, 아니면 ''."""
    ko = re.sub(r"\s+", " ", ko or "").strip().strip("\"'“”‘’ ")
    if not ko or ko == "(없음)" or len(_HANGUL.findall(ko)) < (5 if len(en) >= 40 else 2) or _REFUSE.search(ko):   # 설명이 짧으면('Consultation paper') 번역도 짧다
        return ""
    if not (0.2 * len(en) <= len(ko) <= 2.5 * len(en)):               # 터무니없이 짧거나(요약) 긴(덧붙임) 번역
        return ""
    both = en + " " + title_en
    return ko if _latin_ok(ko, both) and _numbers_ok(ko, both) else ""


def parse(raw: str) -> tuple:
    """모델 출력 → (제목, 설명) 원문 문자열. 형식이 다르면 ('', '')."""
    raw = (raw or "").replace("**", "").replace("`", "")                # 모델이 굵게·코드 표시를 붙여도 읽는다
    t = re.search(r"^\s*제목\s*[:：]\s*(.+?)\s*$", raw, re.M)
    d = re.search(r"^\s*설명\s*[:：]\s*(.*)\Z", raw, re.M | re.S)
    return (t.group(1) if t else ""), (d.group(1) if d else "")


def claude_translate(title: str, desc: str, ccfg: dict, fg, smr) -> tuple:
    """항목 1건 → (제목_ko, 설명_ko). 실패한 쪽은 ''. 인증·한도 오류면 smr._CLAUDE_DEAD를 켠다."""
    c = dict(ccfg["summarizer"]["claude_fallback"])
    c["cli_system"] = "당신은 영한 번역기입니다. 지시한 두 줄 형식(제목·설명)만 출력합니다."
    c["cli_model"] = ccfg.get("reports", {}).get("translate", {}).get("model") or c.get("cli_model", "haiku")
    if smr._CLAUDE_DEAD:
        return "", ""
    raw = None
    for _ in range(2):                                                 # 호출 자체가 실패한 경우만 다시(형식·검증 실패는 같은 결과)
        try:
            raw, tin, tout = smr._claude_call_cli(PROMPT.format(title=title, desc=desc or "(없음)"), c)
            smr.CLAUDE_USAGE["calls"] += 1; smr.CLAUDE_USAGE["in"] += tin; smr.CLAUDE_USAGE["out"] += tout
            break
        except smr._ClaudeFatal as e:
            smr.CLAUDE_LAST_ERR = str(e); smr._CLAUDE_DEAD = True
            return "", ""
        except smr._ClaudeBusy as e:
            time.sleep(e.wait)
        except Exception:
            time.sleep(2)
    if raw is None:
        return "", ""
    t_raw, d_raw = parse(raw)
    return fg.valid_title_ko(t_raw, title), valid_desc_ko(d_raw, desc, title) if desc else ""


def translate_store(store: dict, cfg: dict, translate_fn=None, check_claude: bool = None, now_fn=time.time) -> dict:
    """저장소의 영문 항목에 title_ko·desc_ko를 채운다(제자리 수정). → 통계 dict.
    translate_fn(title, desc) → (제목_ko, 설명_ko)는 시험에서 가짜 번역기를 넣는 자리."""
    tc = cfg.get("reports", {}).get("translate", {})
    stats = {"done": 0, "failed": 0, "skipped": 0, "pending": 0, "no_claude": 0}
    if not tc.get("enabled", True):
        return stats
    todo = [i for i in store.get("items", []) if needs_translation(i) and _incomplete(i)]
    if not todo:
        return stats
    smr = None
    if translate_fn is None:
        import foreign as fg                                           # 지연 import — 번역을 안 쓰는 실행·시험은 이 의존을 끌어오지 않는다
        import summarizer as smr
        ccfg = fg.claude_cfg(cfg)
        if (check_claude is None or check_claude) and not fg.claude_ready(ccfg):
            print("  ⚠ 구독 Claude(CLI·CLAUDE_CODE_OAUTH_TOKEN)가 없어 번역을 건너뜁니다 — 영문 그대로 표시(%d건)" % len(todo))
            stats["no_claude"] = 1; stats["pending"] = len(todo)
            return stats
        translate_fn = lambda t, d: claude_translate(t, d, ccfg, fg, smr)
    todo.sort(key=lambda i: (i["date"], i.get("first_seen", "")), reverse=True)        # 새 항목부터
    cap = tc.get("max_per_run", 80)
    budget = tc.get("max_seconds", 720)
    t0 = now_fn()
    for n, it in enumerate(todo):
        if n >= cap or now_fn() - t0 > budget:
            stats["pending"] = len(todo) - n                           # 남은 건 다음 실행에서(그동안은 영문 그대로)
            break
        if smr is not None and smr._CLAUDE_DEAD:
            print("  ⚠ 구독 Claude 오류로 번역 중단:", smr.CLAUDE_LAST_ERR)
            stats["no_claude"] = 1; stats["pending"] = len(todo) - n
            break
        it["tr_tries"] = it.get("tr_tries", 0) + 1
        try:
            t_ko, d_ko = translate_fn(it["title"], it.get("desc", ""))
        except Exception as e:                                         # 번역 한 건의 실패가 나머지를 막지 않게
            print("  번역 오류:", str(e)[:80])
            t_ko, d_ko = "", ""
        if smr is not None and smr._CLAUDE_DEAD and not t_ko:      # 인증·한도 오류는 항목의 잘못이 아니다 — 시도 횟수를 쓰지 않고 중단
            it["tr_tries"] -= 1
            print("  ⚠ 구독 Claude 오류로 번역 중단:", smr.CLAUDE_LAST_ERR)
            stats["no_claude"] = 1; stats["pending"] = len(todo) - n
            break
        if t_ko:
            it["title_ko"] = t_ko
        if d_ko:
            it["desc_ko"] = d_ko
        stats["done" if t_ko else "failed"] += 1
    print("  번역: 이번 %d건 성공 · %d건 실패 · 남음 %d건 (호출 1건당 제목+설명 1회)" % (stats["done"], stats["failed"], stats["pending"]))
    return stats


def _incomplete(it: dict) -> bool:
    """아직 번역이 끝나지 않았고 시도 횟수가 남았는가."""
    if it.get("tr_tries", 0) >= MAX_TRIES:
        return False
    return not it.get("title_ko") or (bool(it.get("desc")) and not it.get("desc_ko"))
