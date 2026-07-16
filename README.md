# 금융회사 디지털·AI 뉴스 수집 시스템

국내외 금융회사의 디지털·AI 뉴스를 수집·요약해 웹 아카이브로 만드는 시스템. **운영비 0원** (네이버 API 무료 + Groq 무료 + GitHub 무료).

- **결과 보기** → https://yeo6119-commits.github.io/financial-news/financial_news_archive.html
- **저장소** → https://github.com/yeo6119-commits/financial-news

---

## 이 시스템이 하는 일

```
네이버 뉴스 API (985개 검색어)  ─┐
                                 ├─→ 수집 ~1,800건
9개 금융그룹 보도자료 크롤링    ─┘        │
                                          ▼
                        1차 스크리닝 (제목만으로 판정)      ~1,800 → ~300
                                          ▼
                        본문 추출 (병렬 16스레드)
                                          ▼
                        2차 필터 (본문 리드 읽고 최종 판정)
                                          ▼
                        중복 제거 (회차 내 + 회차 간)        ~300 → 20~50
                                          ▼
                        분류 (그룹·회사·업권·AI/디지털)
                                          ▼
                        Groq 요약 (1건씩, 개조식 2~3줄)
                                          ▼
                        HTML 아카이브 → GitHub Pages
```

**실행 시간** 6~10분 · **1회 API 호출** 약 3,900콜 (네이버 일일 한도 25,000)

---

## 수정할 때

```bash
cd ~/Projects/financial-news
./sync.sh "수정 내용"
```

다운로드 폴더의 최신 파일을 가져오고, 회귀 검사를 돌린 뒤, 통과해야 push한다. 자세한 내용은 [docs/project-management.md](docs/project-management.md).

---

## 하루 사용법

1. 페이지 상단 **[실행]** 버튼 클릭 (또는 아이폰 GitHub 앱 → Actions → Run workflow)
2. 6~10분 후 자동 새로고침
3. 완료 화면의 토큰 사용량 확인 → `→ 토큰 사용 70b 42,000/100,000 (42%)`

> **하루 1~2회를 권장.** 24시간 창으로 검색하므로 하루 한 번이면 충분하다.
> 자주 돌리면 이미 본 기사는 "기열람"으로 걸러져 0건이 나오고, Groq 쿼터만 소모된다.

---

## 문서

| 문서 | 내용 |
|---|---|
| [docs/architecture.md](docs/architecture.md) | 파이프라인 8단계, 모듈별 역할, 데이터 흐름 |
| [docs/configuration.md](docs/configuration.md) | `config.yaml` 전체 항목, 튜닝 포인트 |
| [docs/filtering.md](docs/filtering.md) | 필터 규칙 전체 — **가장 자주 손보는 부분** |
| [docs/summarization.md](docs/summarization.md) | 요약 형식, Groq 토큰 관리, 레이트리밋 대응 |
| [docs/operations.md](docs/operations.md) | 실행·배포·git 워크플로·트러블슈팅 |
| [docs/decisions.md](docs/decisions.md) | 설계 결정과 이유 — **건드리면 안 되는 것들** |
| [docs/project-management.md](docs/project-management.md) | 폴더 구조, 회귀 검사, 파일 주고받기 |

---

## 파일 구조

```
financial_news_v2.3/
├── config.yaml            # 모든 설정 — 대부분의 튜닝은 여기서
├── main.py                # 파이프라인 오케스트레이션
│
├── collector.py           # 네이버 API 수집 (8스레드)
├── press_collector.py     # 9개 금융그룹 보도자료 크롤링
├── extractor.py           # 본문 추출 (16스레드)
├── filter.py              # 1차 스크리닝 + 2차 필터
├── deduplicator.py        # 중복 제거 (회차 내 + 회차 간)
├── classifier.py          # 그룹·회사·업권·AI/디지털 분류
├── summarizer.py          # Groq 요약 + 토큰 관리
├── html_generator.py      # HTML 아카이브 생성
├── db.py                  # SQLite (news.db)
│
├── rerender.py            # 재수집 없이 HTML만 다시 생성
├── retry_summary.py       # 요약 실패분만 재시도 (쿼터 회복 후)
├── migrate_company.py     # 회사명 정규화 DB 일괄 교정
├── diagnose.py            # 필터 진단 (반영 0건일 때)
│
├── check.sh               # 회귀 검사 — 반복 재발한 수정이 살아있는지
├── sync.sh                # 다운로드 정리 + 검사 + push 를 한 번에
│
└── .github/workflows/run.yml
```

---

## 핵심 원칙

1. **어떤 기사도 조용히 사라지지 않는다** — 제외 기사는 사유와 함께 HTML 하단에 표시
2. **수집은 넓게, 판단은 본문 확보 후 로컬에서** — 검색 단계에서 미리 좁히지 않는다
3. **요약 배치 금지** — 기사 1건 = Groq 호출 1회. 배치는 기사 유실의 원인이었다
4. **실패해도 기사는 보존** — 요약 실패 시 [요약 실패] 카드로 표시, 제목·링크는 살린다

---

## 처음 세팅하는 경우

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

`.env` 파일 작성:
```
NAVER_CLIENT_ID=발급받은ID
NAVER_CLIENT_SECRET=발급받은Secret
GROQ_API_KEY=발급받은키
```

- 네이버 API: developers.naver.com → 애플리케이션 등록 → 검색 API
- Groq: console.groq.com → API Keys

GitHub Actions로 돌리려면 저장소 Secrets에 위 3개를 등록한다. 자세한 내용은 [docs/operations.md](docs/operations.md).
