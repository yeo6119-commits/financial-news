# 운영

---

## 역할 분담

| 기기 | 용도 |
|---|---|
| **아이폰 / 브라우저** | 실행 전용 |
| **맥북** | 코드 수정 전용 |

이 분리가 중요하다. 맥북에서 실행하면 로컬 `news.db`와 GitHub의 `news.db`가 충돌한다.

---

## 실행

### 방법 1 — HTML 실행 버튼 (권장)

1. 아카이브 페이지 상단 **[실행]** 클릭
2. 처음이면 GitHub 토큰 입력 (브라우저당 1회)
3. 진행 상황이 표시되고, 완료되면 자동 새로고침

토큰은 브라우저 `localStorage`에만 저장된다. HTML 소스나 서버에는 없으므로 공개 저장소여도 남이 실행할 수 없다.

### 방법 2 — GitHub 앱

아이폰 GitHub 앱 → Actions → "금융 뉴스 수집" → Run workflow

> Node 20 deprecation 경고는 무시해도 된다.

---

## GitHub 토큰 발급

Settings → Developer settings → **Personal access tokens (classic)** → Generate new token (classic)

**필요 권한**: `repo`, `workflow`

- 생성 직후 한 번만 보이므로 **메모나 비밀번호 관리자에 저장**할 것
- 하나의 토큰을 여러 기기에서 재사용 가능 (브라우저마다 한 번씩 입력)
- 맥북 터미널 push용 PAT에 `workflow` 권한이 있으면 그것도 그대로 쓸 수 있다
  ```bash
  security find-internet-password -s github.com -w    # 키체인에서 꺼내기
  ```

---

## 코드 수정 → 배포

```bash
cd ~/Downloads/financial_news_v2.3
git pull --no-edit && git add -A && git commit -m "수정 내용" && git push
```

`git pull --no-edit`가 핵심이다. rejected가 나도 자동 병합되고 vim이 안 열린다.

### 다운로드 파일 이름에 번호가 붙을 때

```bash
ls -lt ~/Downloads | grep -E "filter|config" | head -5
mv "$HOME/Downloads/filter (1).py" filter.py
```

옮긴 뒤 `~/Downloads`의 사본을 지우면 다음부터 깔끔한 이름으로 받아진다.

### 제대로 반영됐는지 확인

```bash
git log --oneline -3
git show origin/main:summarizer.py | grep -c "compact_body"    # 1 이상이면 GitHub 반영됨
```

`HEAD -> main, origin/main`이 같은 커밋을 가리키면 동기화 완료.

---

## GitHub Secrets

저장소 Settings → Secrets and variables → Actions

| 이름 | 값 |
|---|---|
| `NAVER_CLIENT_ID` | 네이버 개발자센터 |
| `NAVER_CLIENT_SECRET` | 네이버 개발자센터 |
| `GROQ_API_KEY` | console.groq.com |
| `ANTHROPIC_API_KEY` | console.anthropic.com (선택) — Groq 두 모델이 일일한도를 소진했을 때만 Claude Haiku가 요약을 대신한다. 없으면 건너뛴다. Claude 구독과는 별개로 API 크레딧이 필요하다 |
| `CLAUDE_CODE_OAUTH_TOKEN` | 로컬에서 `claude setup-token` 실행 — 국내는 선택(API 키 대신 구독 한도로 대체 요약, 둘 다 있으면 API 키 우선), **해외 영문 트랙은 필수**. 토큰은 만든 사람의 구독에 묶인다 |

---

## DB 충돌이 없는 이유

| 조치 | 효과 |
|---|---|
| `.gitignore`에 `news.db` | 맥북 push 시 DB가 안 딸려감 |
| `run.yml`의 `git add -f news.db` | Actions는 gitignore를 무시하고 DB를 강제 커밋 |

맥북은 DB를 안 올리고, Actions만 올린다. 그래서 충돌이 구조적으로 발생하지 않는다.

---

## 해외(영문) 트랙 — 국내와 별도 운영

국내 뉴스(`run.yml`)와 **파일·워크플로·한도가 모두 따로**다. 국내 실행에는 영향이 없다.

| 항목 | 국내 | 해외 |
|---|---|---|
| 워크플로 | `run.yml` (KST 06:47·08:13) | `foreign.yml` (KST 12:23·18:17·23:41) + 수동 실행 |
| 수집 | 네이버 API | Bing 뉴스 RSS(주) + 구글 뉴스 RSS(보조, 링크 해독 15회·연속 3회 실패 시 중단) |
| 요약 | Groq(소진 시 Claude 대체) | **구독 Claude만** (`CLAUDE_CODE_OAUTH_TOKEN` 필수 — 없으면 수집 자체를 생략하고 워크플로가 빨간불) |
| 저장 | `news.db` | `foreign/data/YYYY-MM-DD.json` (날짜별, 영구 보관) |
| 페이지 | `output/financial_news_archive.html` | `output/foreign.html` (국내 메뉴 끝에 "해외 영문 ↗" 링크) |
| 커밋 대상 | news.db·국내 HTML·archive | foreign/data·output/foreign.html (겹치지 않아 rebase 충돌 없음) |

- **실행 버튼**: 국내 페이지의 [실행]은 국내(`run.yml`), [해외 실행]은 해외(`foreign.yml`)만 시작한다. 둘을 동시에 눌러도 병렬로 돈다
  (수집 작업은 concurrency 그룹이 달라 서로 기다리지 않는다). 버튼마다 상태·진행 확인이 따로이고, 국내가 끝나도 해외가 도는 중이면
  새로고침을 미룬다. 다만 **Pages 배포 단계만은 한 줄로 세운다**(`pages-deploy` 그룹) — 둘이 거의 동시에 끝나면 배포가 겹쳐 둘째가 실패한다.
  같은 토큰(repo·workflow 권한)을 쓴다.
- **국내 페이지에 같이 표시**: 해외 기사는 국내 페이지의 회차 블록과 같은 모양(`2026-10-29 09:51 요청분 · 해외 영문 · 10건`)으로
  요청 시각 순서에 끼어 보이고, '전체'와 '해외' 탭에서 보인다(다른 탭에서는 숨음). 국내 HTML 파일은 해외 실행이 만들지 않는다 —
  해외 실행은 `output/foreign_feed.json`만 올리고, 국내 페이지가 열릴 때 이 파일을 읽어 끼워 넣는다(파일이 없으면 국내만 보임).
  제외된 후보와 사유는 `foreign.html`에서 본다.
- 대상: `config.yaml`의 `foreign.companies` 12곳. 하루 최대 20건, 회사당 3건, 한 실행 10건.
- 주가·시황 기사(차단 출처, 분석성 제목)는 제외한다. 유료 매체는 **본문이 실제로 읽힐 때만** 반영하고, 못 읽으면
  페이지의 "반영하지 않은 후보"에 사유와 함께 남는다(조용히 사라지는 기사 없음).
- 처음 한 번: 로컬에서 `claude /login` → `claude setup-token` → 저장소 Secrets에 `CLAUDE_CODE_OAUTH_TOKEN` 등록
  (웹/채팅에 토큰을 붙여넣지 말 것) → Actions → **해외 영문 뉴스** → Run workflow.
- 반영 0건이면: 페이지 맨 아래 제외 사유부터 본다. `본문 접근 불가`가 많으면 매체 차단, `구독 Claude 오류`면 토큰·한도.
- 로컬에서 `foreign.py`를 돌리면 `foreign/data`에 쓰고 원격과 충돌한다 — 시험은 임시 폴더(`foreign.run(cfg, root=...)`)로.

---

## 보조 스크립트

| 스크립트 | 용도 |
|---|---|
| `rerender.py` | 재수집 없이 HTML만 다시 생성 (HTML 코드 고쳤을 때) |
| `retry_summary.py` | 요약 실패분만 재시도 (쿼터 회복 후) |
| `migrate_company.py` | 회사명 정규화 DB 일괄 교정 (`BRAND_TO_COMPANY` 바꿨을 때) |
| `diagnose.py` | 필터 진단 (반영 0건일 때) |

```bash
source venv/bin/activate
python retry_summary.py 30
```

---

## 트러블슈팅

### 워크플로 빨간불

**`cannot VACUUM from within a transaction`**

`db.py`의 `cleanup()`에서 VACUUM이 트랜잭션 안에 있으면 발생한다. 이 순서를 지켜야 한다:

```python
conn.commit()
conn.isolation_level = None      # autocommit 전환
conn.execute("VACUUM")
conn.isolation_level = ""        # 복구
```

> 이 수정이 **5번 반복해서 날아간 이력**이 있다. `db.py`를 새로 만들 때마다 이 부분을 빠뜨렸기 때문. 수정 시 반드시 보존할 것.

### 반영 0건

수지 라인의 **흐름**을 본다.

```
흐름: 수집 1823 → 1차통과 312 → 중복제거후 0 → 반영 0
```

| 증상 | 원인 | 대응 |
|---|---|---|
| 1차통과 정상, 중복제거후 0 | **정상** — 오늘 이미 돌려서 다 기열람 | 내일 실행 |
| 1차통과 0 | 필터 버그 | `python diagnose.py` |

> `추출실패 0 · 요약실패 0`은 오해를 부른다. 이 통계는 `live`(중복 제거 후) 기준이라, 반영이 0이면 자동으로 0이 된다. "추출이 안 돌았다"는 뜻이 아니다.

### 실행 시간이 길다 (15분 이상)

실행 로그("뉴스 수집 실행" 단계) 끝의 **단계별 소요** 표에서 어느 단계가 느린지 먼저 본다. 단계마다 `⏱ 이름: 시간` 줄도 찍히므로
중간에 끊긴 실행도 어디까지 갔는지 보인다. "검토·요약·저장" 줄에는 검토 기다림/요약 호출/건수·건당 평균이 나뉘어 나오고,
요약 한 건이 60초를 넘으면 그 줄 끝에 `⏱ 느림`이 붙는다(한도 대기·Claude 호출 지연 의심).

본문 추출 대상이 과도한 것. 로그의 `1차 스크리닝: N건 → M건 통과`에서 M을 본다.

- M이 500 이상 → `NON_DIGITAL_TOPICS`에 주제를 추가해 본문 확인 대상을 줄인다
- 정상 범위: 200~350

### 요약이 제목과 다른 내용

**예시 복창.** 근거 검증(`_grounded`)이 잡아내지만, 그 기사의 본문 추출이 실패한 것이므로 매체 페이지 구조를 확인해야 한다. `retry_summary.py`로 본문을 다시 긁으면 해결되기도 한다.

### PR 어댑터 실패 (`hana`, `shinhan`, `woori`)

보도자료 사이트가 500을 반환하거나 구조가 바뀐 경우. 해당 회사 뉴스는 네이버 API로도 커버되므로 치명적이지 않다.

---

## 정기 점검

| 주기 | 항목 |
|---|---|
| 매 실행 | 토큰 사용량, 수지 라인 |
| 주 1회 | 제외 목록에서 오탐 확인 |
| 월 1회 | DB 크기 (`ls -lh news.db`) — 233KB 내외가 정상 |
