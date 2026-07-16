# 프로젝트 관리

---

## 원본은 GitHub 저장소다

```
GitHub (원본)  ←→  ~/Projects/financial-news (작업 사본)  →  GitHub Actions (실행)
```

맥북 폴더가 날아가도 `git clone`으로 복구된다. 별도 백업은 필요 없다.

**단, `.env`는 저장소에 없다.** (API 키라 `.gitignore` 처리) 이 파일만 비밀번호 관리자나 메모에 따로 보관해 둘 것.

---

## 폴더 위치

`~/Downloads`에 두지 말 것. 다운로드 파일과 프로젝트 파일이 같은 공간에서 섞여 `filter (1).py` 같은 사본이 생긴다.

```bash
mkdir -p ~/Projects
mv ~/Downloads/financial_news_v2.3 ~/Projects/financial-news
cd ~/Projects/financial-news && git status
```

---

## 일상 워크플로

### 수정할 때

```bash
cd ~/Projects/financial-news
./sync.sh "수정 내용"
```

`sync.sh`가 하는 일:
1. 다운로드 폴더에서 최신 파일을 가져온다 (`(1)`, `(2)` 붙은 것도 처리)
2. **회귀 검사** 실행 — 실패하면 push를 막는다
3. 변경 내용을 보여주고 확인받은 뒤 commit + push

### 실행할 때

페이지 상단 [실행] 버튼. 또는 아이폰 GitHub 앱 → Actions.

---

## 회귀 검사 (`check.sh`)

**반복해서 날아갔던 수정**이 살아 있는지 확인한다.

```bash
./check.sh
```

```
회귀 검사
────────────────────────────────────────────
  ✓ VACUUM 트랜잭션 수정 (5회 재발 이력)
  ✓ 요약 배치 금지
  ✓ KB 단독 키워드 없음 (KBO 오매칭 방지)
  ✓ 스포츠 키워드에 일반어 없음
  ✓ 요약 근거 검증 (예시 복창 차단)
  ✓ 짧은 본문 호출 생략
  ✓ 한국어 조사 제거
  ✓ 본문확인 대상 축소 (실행시간)
  ✓ 본문 판정 핵심 키워드
────────────────────────────────────────────
  ✓ 전체 문법 정상

통과 — push 해도 됩니다
```

### 왜 필요한가

VACUUM 수정이 **5번 날아갔다.** 파일을 새로 만들 때마다 그 부분이 빠졌기 때문이다. 사람이 매번 기억하는 건 무리다. 기계가 확인하게 한다.

검사 항목은 모두 **실제 사고 이력**이 있는 것들이다. 자세한 내용은 [decisions.md](decisions.md)의 "실패 이력" 표 참조.

### 항목 추가하기

새 사고가 생기면 `check.sh`에 한 줄 추가한다.

```bash
need <파일> <있어야 할 문자열> <설명>
deny <파일> <있으면 안 되는 문자열> <설명>
```

---

## 파일을 주고받을 때

**Claude에게 수정을 요청할 때는 "저장소에서 최신 코드 받아서 고쳐줘"라고 하면 된다.**

저장소가 public이라 Claude가 직접 `git clone`으로 현재 코드를 받을 수 있다. 이러면 낡은 작업본을 덮어쓰는 사고가 구조적으로 생기지 않는다.

받은 파일은 다운로드 폴더에 두고 `./sync.sh`를 돌리면 알아서 정리된다.

---

## 상태 확인

### 로컬과 GitHub이 같은가

```bash
git log --oneline -3
```
`HEAD -> main, origin/main`이 같은 커밋을 가리키면 동기화 완료.

### 특정 수정이 GitHub에 반영됐는가

```bash
git show origin/main:db.py | grep -c isolation_level    # 1 이상이면 반영됨
```

### DB 크기

```bash
ls -lh news.db      # 233KB 내외가 정상. MB 단위면 cleanup 확인
```

---

## 무엇을 저장소에 두고 무엇을 빼는가

| 항목 | 저장소 | 이유 |
|---|---|---|
| 코드, config, 문서 | ○ | 원본 |
| `news.db` | △ | `.gitignore` 처리하되 Actions만 `git add -f`로 커밋 |
| `output/*.html` | ○ | GitHub Pages가 서빙 |
| `.env` | ✕ | API 키 |
| `venv/` | ✕ | 환경마다 다름 |

`news.db`를 gitignore에 넣은 이유: 맥북에서 push할 때 DB가 딸려가면 Actions가 만든 DB와 충돌한다. 맥북은 안 올리고 Actions만 올리게 해서 충돌을 구조적으로 없앴다.

---

## 정기 점검

| 주기 | 항목 |
|---|---|
| 매 실행 | 토큰 사용량, 수지 라인 |
| 주 1회 | 제외 목록에서 오탐 확인 |
| 월 1회 | DB 크기, `./check.sh` |
| 분기 1회 | GitHub 토큰 만료 확인 (90일 설정 시) |
