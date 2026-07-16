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

---

## DB 충돌이 없는 이유

| 조치 | 효과 |
|---|---|
| `.gitignore`에 `news.db` | 맥북 push 시 DB가 안 딸려감 |
| `run.yml`의 `git add -f news.db` | Actions는 gitignore를 무시하고 DB를 강제 커밋 |

맥북은 DB를 안 올리고, Actions만 올린다. 그래서 충돌이 구조적으로 발생하지 않는다.

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
