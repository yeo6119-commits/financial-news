# 설정 (`config.yaml`)

대부분의 튜닝은 코드를 건드리지 않고 이 파일에서 끝난다.

---

## 자주 만지는 것 3가지

| 하고 싶은 것 | 바꿀 항목 | 현재값 |
|---|---|---|
| 요약이 부실하다 | `summarizer.body_chars` ↑ (1400~1800) | `1100` |
| Groq 한도가 빠듯하다 | `summarizer.body_chars` ↓ (900) | `1100` |
| 회사를 추가한다 | `tier1` / `tier2`의 해당 그룹 | — |

---

## `time`

```yaml
time:
  window_hours: 24        # 요청 시각 기준 최근 N시간
```

**직전 실행 시각 기준이 아니라 고정 24시간.** 매일 안 돌릴 수도 있으니 일관성을 위해 고정했다.

> 감수사항: 하루 이상 건너뛰면 그 사이 기사는 못 잡는다. 대신 자주 돌려도 "기열람" 중복 제거가 있어 같은 기사가 반복 노출되지 않는다.

---

## `naver_api`

```yaml
naver_api:
  display: 100            # 1회 요청당 기사 수 (최대 100)
  max_start: 1000         # 페이지네이션 상한 (네이버 제한)
  sort: date
  stop_rule: full_page_old    # 24시간보다 오래된 페이지 나오면 중단
  extra_page_after_old: 1
  daily_call_limit: 25000
```

1회 실행에 약 **3,900콜**. 일일 한도 25,000이므로 하루 6회까지는 안전하다.

---

## `summarizer` — 토큰 관리의 핵심

```yaml
summarizer:
  provider: groq
  model: llama-3.3-70b-versatile      # 주 모델
  fallback_model: llama-3.1-8b-instant  # 70b 일일한도 소진 시 자동 전환
  body_chars: 1100        # 요약에 보낼 본문 길이 ← 토큰의 70%가 여기
  min_body_chars: 200     # 이보다 짧으면 Groq 호출 생략
  max_tokens: 180
  batch: false            # ★ 절대 true로 바꾸지 말 것
  max_retries: 3
  backoff_base_seconds: 2
  validation:
    min_lines: 2
    max_lines: 3
    each_starts_with: "-"
    min_line_chars: 15
```

### `body_chars`가 가장 중요하다

건당 토큰의 약 70%가 본문이다. 이 값 하나로 하루 처리량이 결정된다.

| `body_chars` | 건당 토큰 | 70b 하루 | 70b+8b 하루 |
|---|---|---|---|
| 3000 (최초) | 3,275 | 30건 | 61건 |
| 1500 | 2,088 | 47건 | 95건 |
| **1100 (현재)** | **1,673** | **59건** | **119건** |
| 900 | ~1,470 | 68건 | 136건 |

문장 단위로 자르므로 1,100자면 보통 6~8문장이 들어간다. 한국 기사는 역피라미드라 그 안에 5W1H와 핵심 수치가 다 있다.

### 사용하지 않는 잔여 키

`style`, `lines`, `line_prefix`, `rules` 는 프롬프트를 재작성하면서 코드에서 안 쓰게 됐다. 지워도 무방하나 남아 있어도 동작에 영향 없다.

---

## `dedup`

```yaml
dedup:
  title_similarity_threshold: 0.62
  body_fingerprint: simhash
```

코드에 하드코딩된 임계값도 있다 (`deduplicator.py`):

| 위치 | 조건 | 값 |
|---|---|---|
| 회차 내 | 같은 날 + 토큰 겹침 | `0.35` |
| 회차 내 | 토큰 겹침 (날짜 무관) | `0.5` |
| 회차 내 | 본문 simhash 해밍 | `6` |
| 회차 간 | 본문 simhash 해밍 | `3` |
| 회차 간 | 제목 토큰 겹침 | `0.5` |

**너무 많이 묶이면** 0.35 → 0.45로 올린다. **안 묶이면** 0.35 → 0.30으로 내린다.

---

## `db`

```yaml
db:
  path: news.db
  retention_days: 60              # 반영 기사 보관 (제외 기사는 저장 안 함)
  store_full_body: false          # 본문 미저장 (DB 크기 절감)
  delivered_after_html_success: true
```

---

## `filters`

| 키 | 개수 | 용도 |
|---|---|---|
| `sports_exclude` | 30 | KBO·탈삼진·시청률 등 스포츠 전용어만 |
| `crime_exclude` | 12 | 범죄 기사 |
| `security_override` | 9 | 보이스피싱·FDS 등 — 범죄 필터보다 우선 |
| `promo_exclude_hint` | 4 | 프로모션 힌트 |

> **주의**: `sports_exclude`에 "경기", "시즌", "리그", "우승"을 넣으면 안 된다. 경기도·경기전망·시즌프로모션·공모전우승 기사가 잘린다. 실제로 그랬다가 되돌린 이력이 있다.

상세 규칙은 [filtering.md](filtering.md).

---

## `tier1` — 5대 금융지주 + 인터넷·핀테크

```yaml
tier1:
  하나금융:
    menu_id: hana
    group_keywords: [하나금융그룹, 하나금융지주, 하나금융]
    companies:
      은행: [하나은행, ...]
      증권: [하나증권, ...]
```

| 그룹 | menu_id | 회사 수 | standalone |
|---|---|---|---|
| 하나금융 | `hana` | 12 | — |
| 신한금융 | `shinhan` | 10 | — |
| KB금융 | `kb` | 14 | — |
| 우리금융 | `woori` | 10 | — |
| NH농협금융 | `nh` | 14 | — |
| 인터넷은행핀테크 | `internet` | 13 | **true** |

**`standalone_mode: true`** 는 회사명이 그대로 검색어가 된다는 뜻. 인터넷·핀테크만 이 방식이다.

> `KB`를 `group_keywords`에 단독으로 넣으면 **`KBO`가 매칭된다.** 실제로 야구 기사가 들어왔던 원인. 정식 명칭만 쓸 것.

---

## `tier2` — 비지주 금융사

| 그룹 | menu_id | 회사 수 |
|---|---|---|
| 지방금융 | `regional` | 16 |
| 국책특수 | `policy` | 9 |
| 비지주증권 | `securities` | 27 |
| 비지주카드보험 | `cardins` | 19 |

---

## `html`

```yaml
html:
  output_file: output/financial_news_archive.html
  menu_order: [all, hana, shinhan, kb, woori, nh,
               regional, policy, securities, cardins, internet, overseas]
  group_articles_by: run_datetime
  excluded_section: collapsible
```

---

## `github` — 실행 버튼용

```yaml
github:
  owner: yeo6119-commits
  repo: financial-news
  workflow: run.yml
  branch: main
```

HTML의 [실행] 버튼이 이 정보로 GitHub Actions를 호출한다. 토큰은 브라우저 `localStorage`에만 저장되고 HTML 소스에는 없다.

---

## 회사를 추가하는 법

1. 해당 그룹의 `companies`(tier1) 또는 `subgroups`(tier2)에 회사명 추가
2. 앱·서비스 브랜드가 있으면 `classifier.py`의 `BRAND_TO_COMPANY`에도 추가
   ```python
   "새로운앱": "회사명",
   ```
   → 브랜드명은 자동으로 관련성 키워드가 되므로, 제목에 앱 이름만 있어도 수집된다
3. 기존 DB의 회사명을 일괄 교정하려면 `python migrate_company.py`
