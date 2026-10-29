#!/bin/bash
# 회귀 검사 — 반복해서 날아갔던 수정들이 살아 있는지 확인
# push 전에 자동 실행된다. 실패하면 push를 막는다.
cd "$(dirname "$0")"
fail=0

need() {   # need <파일> <찾을문자열> <설명>
  if grep -q "$2" "$1" 2>/dev/null; then
    printf "  ✓ %s\n" "$3"
  else
    printf "  ✗ %s  — %s 에 '%s' 없음\n" "$3" "$1" "$2"
    fail=1
  fi
}

deny() {   # deny <파일> <있으면안되는문자열> <설명>
  if grep -q "$2" "$1" 2>/dev/null; then
    printf "  ✗ %s  — %s 에 '%s' 있음\n" "$3" "$1" "$2"
    fail=1
  else
    printf "  ✓ %s\n" "$3"
  fi
}

echo "회귀 검사"
echo "────────────────────────────────────────────"
# 5번 날아갔던 수정
need db.py         "isolation_level"      "VACUUM 트랜잭션 수정 (5회 재발 이력)"
# 배치 금지
need config.yaml   "batch: false"         "요약 배치 금지"
# 오탐 사고 재발 방지
deny config.yaml   "KB금융, KB\]"          "KB 단독 키워드 없음 (KBO 오매칭 방지)"
for w in 경기 시즌 리그 우승; do
  if sed -n '/sports_exclude/,/^  [a-z_]*:/p' config.yaml | grep -q "[ ,\[]$w[ ,\]]"; then
    printf "  ✗ 스포츠 키워드에 '%s' 있음 (일반어 오탐)\n" "$w"; fail=1
  fi
done
[ $fail -eq 0 ] && printf "  ✓ 스포츠 키워드에 일반어 없음\n"
# 요약 안전장치
need summarizer.py "_grounded"            "요약 근거 검증 (예시 복창 차단)"
need summarizer.py "min_body_chars"       "짧은 본문 호출 생략"
need summarizer.py "_summarize_claude"    "Groq 소진 시 Claude 대체 요약"
need summarizer.py "_grounded_en"         "영문 기사 번역요약 근거 검사(예시복창·회사 일치)"
need summarizer.py "EN_NOTE"             "영문 본문이면 번역 지시를 프롬프트에 추가"
need backfill.py   "retry_english"       "영문 기사 환각 폐기분 1회 재요약"
need summarizer.py "_DAILY_OUT"           "소진된 Groq 모델 재호출 생략"
need main.py       "backfill.run"         "한도 실패 요약 자동 보충 연결"
need backfill.py   "LIMIT_REASONS"        "보충은 한도 실패만 대상(환각 등 재시도 금지)"
need summarizer.py "_NOUN_KEEP"           "어미 보정이 명사 끝글자를 자르지 않게(증가→증 방지)"
need .github/workflows/run.yml "ANTHROPIC_API_KEY" "Claude 대체 요약 키 주입"
need .github/workflows/run.yml "CLAUDE_CODE_OAUTH_TOKEN" "Claude 구독 토큰 주입(CLI 대체 요약)"
need summarizer.py "_claude_call_cli"     "Claude CLI 경로(구독 한도 사용)"
# 중복 제거
need deduplicator.py "_strip_josa"        "한국어 조사 제거"
need deduplicator.py "_matches"            "전이적 클러스터링 (대표만 비교하면 사건이 쪼개짐)"
# 필터
need filter.py     "NON_DIGITAL_TOPICS"   "본문확인 대상 축소 (실행시간)"
need filter.py     "BODY_CORE"            "본문 판정 핵심 키워드"
need filter.py     "FORECAST_HOUSES"      "외국계IB 시황 전망 필터"
need filter.py     "FINTECH_EXCLUDE"      "핀테크사 M&A·실적 제외"
need filter.py     "HARD_EXCLUDE"         "채용·프로모션 제외 (관련성보다 먼저)"
need filter.py     "펀드"                 "금융상품(펀드·RP·특판) 제외"
need config.yaml   "reviewer:"            "검토 에이전트 설정"
need main.py       "review_ahead"         "검토 에이전트(요약과 동시 진행) 파이프라인 연결"
need filter.py     "프라이빗 뱅킹"          "오프라인 점포·센터 제외"
need filter.py     "PHISHING_ANECDOTE"    "보이스피싱 미담 제외"
need filter.py     "NOT_OUR_COMPANY"      "오매칭 회사 제외 (토스→앱토스랩스)"
need filter.py     "CRYPTO_COLUMN_RE"     "크립토 시황 코너 제외"
need filter.py     "HARD_EXCLUDE_RE"      "수상·시황·세미나 제외"
need config.yaml   "인공지능'·'생성형AI' 제거"  "검색어 슬림화 유지"
need config.yaml   "topic_section"        "업계 동향 검색(회사명 무관)"
need filter.py     "_topic_screen"        "업계 동향 전용 판정"
need .github/workflows/run.yml "list_view.py"  "목록 보기 자동 갱신(list_view.py 실행)"
need .github/workflows/run.yml "article_list.html"  "HTML도 커밋 대상"
need html_generator.py "_render_seen_grouped" "기열람 목록 날짜별 그룹화(기본펼침)"
need deduplicator.py "dedup_by_summary"    "요약 기반 2차 중복(제목 달라도 같은 사건)"
need config.yaml   "AX,"                  "AX(AI전환) 키워드"
need filter.py     "양자내성암호"          "디지털 인프라 용어"
need reviewer.py   "애매하면 YES"          "검토 에이전트 과도제외 방지"
need deduplicator.py "content_overlap"     "회사명·일반어 제외 겹침"
need deduplicator.py "TITLE_GENERIC"       "제목 일반어 목록"
need db.py         "find_delivered_summaries" "회차간 요약 대조"
need db.py         "excluded_log"         "제외 기사 추적 로그"
need config.yaml   "company_aliases"      "회사명 축약형 별칭"
need main.py       "max_catchup_hours"    "공백 따라잡기(뉴스 유실 방지)"
need collector.py  "class Pacer"          "네이버 호출 속도 조절(429·기사 누락 방지)"
need collector.py  "_TRACKING_PARAMS"     "URL 해시가 기사번호 쿼리 보존(idxno)"
need deduplicator.py "_ROUNDUP_RE"         "묶음기사 대표 후순위"
need deduplicator.py "_company_stems"      "회사명 접미사 생략형 대응(KB국민 등)"
need db.py         "url_or_title_delivered" "기열람 원게재 링크 조회"
need html_generator.py "ref_link"          "기열람 원게재 기사 클릭 가능"
need main.py       "dedup_by_summary"      "요약 2차 중복 파이프라인 연결"
need config.yaml   "incremental"          "증분 수집 설정"
need main.py       "overlap_minutes"      "증분 겹침 여유"
need config.yaml   "cross_run_threshold"   "회차 간 중복 완화 임계"
need summarizer.py "fix_ending"          "개조식 어미 기계 보정"
need filter.py     "is_broker_report"     "증권사 종목리포트 제외(어순 무관)"
need filter.py     "KSQI"                 "수상·품질지수 제외"
need deduplicator.py "JOSA_KEEP_TRAILING_I" "조사 '이' 미제거(네이버페이 토큰 보존)"
need extractor.py  "trafilatura"          "본문추출 폴백(비제휴 매체)"
need config.yaml   "policy_section"       "정책·규제 섹션 정의"
need collector.py  "policy_section"       "정책 검색어 생성"
need classifier.py "policy"               "정책 기사 전용 분류"
# 단독 사용 시 일반 은행업무를 통과시킨 이력 (계좌 여세요 이벤트 → '계좌개설')
deny filter.py     '"계좌개설",'           "BODY_CORE에 '계좌개설' 단독 없음"
deny filter.py     '"결제", "QR"'          "BODY_CORE에 '결제' 단독 없음"

need deduplicator.py "회사 충돌 검사를 맨 앞에" "매칭함수 순서(회사충돌 최우선)"
need deduplicator.py "if acomp and pcomp and not" "회차간 판정 회사충돌 가드"
need config.yaml   "summary_dup_threshold: 0.40" "요약중복 임계 실측조정(0.5→0.40)"
need extractor.py  "attempt in range(3)" "접속실패 최대 3회 시도·10초(Actions 간헐 지연 흡수)"
need retry_extract.py "접속 실패"         "본문 접속 실패 기사 다음 실행에서 재추출(유료·구조 문제는 제외)"
need main.py       "retry_extract.run"    "본문 재추출 파이프라인 연결"

need deduplicator.py "rep.get(\"_comp\") and a.get(\"_comp\")" "클러스터 합류시 대표와 회사공유 필수"
need deduplicator.py "body_ok"              "빈 본문 동일판정 차단"
need html_generator.py "len(m) > 3"         "중복목록 기사 링크"

need filter.py     "def is_roundup"        "묶음기사 제외(브리핑·단신·外)"

need .github/workflows/run.yml "pull --rebase" "push 충돌 재시도(실행 실패 방지)"
need config.yaml   "'플랫폼'·'비대면' 제거" "저생산 검색어 정리 유지"

need html_generator.py "rep-out"             "중복 대표 반영여부 배지"

need .github/workflows/run.yml "47 21"  "아침 정기실행(KST 06:47, 지연흡수)"
need .github/workflows/run.yml "13 23"  "백업 실행(KST 08:13)"
need .github/workflows/run.yml "ref: main"   "checkout은 항상 최신 main (대기 실행의 구버전 충돌 방지)"
need .github/workflows/run.yml "rebase --abort" "rebase 충돌 시 원상 복구(충돌 표시 배포 방지)"

need html_generator.py "seen-more"           "기열람 대표1건+더보기 접힘"
need html_generator.py "rep-dup"             "본문무관 반복사건 묶음"
need html_generator.py "copy-sum"            "카드별 공유용 요약 복사 버튼"
need html_generator.py "_share_text"          "공유 문구 [날짜] 회사 + 요약 + 원문링크"
need html_generator.py "shareModal"           "요약 버튼 → 공유 팝업(확인·수정 후 복사)"
need html_generator.py "sim-btn"              "원문 보기 옆 '비슷한 기사' 단추"
need similar.py    "excluded_log"         "비슷한 기사 = 제외 로그의 중복 사유로 대표 카드 연결"
need main.py       "similar.build"        "비슷한 기사 목록 생성 연결(실패해도 렌더링 계속)"
need outlets.py    "og:site_name"         "언론사 이름 = 사이트가 밝힌 이름(추측 금지)"
need main.py       "outlets.refresh"      "새 매체 이름 조회 연결(실패해도 렌더링 계속)"

# 해외(영문) 트랙 — 국내와 분리·영향 차단
need .github/workflows/foreign.yml "foreign-news-pipeline" "해외 워크플로는 별도 concurrency 그룹(국내 실행 취소 방지)"
need .github/workflows/foreign.yml "ref: main"            "해외 워크플로도 최신 main 체크아웃"
need .github/workflows/foreign.yml "rebase --abort"       "해외 워크플로 rebase 충돌 원상 복구"
need foreign.py    "claude_ready"                         "구독 Claude 없으면 수집 생략(요약 불가한 헛수고 방지)"
need foreign.py    "max_per_company_per_day"              "회사당 하루 상한"
need foreign.py    "시황·종목 분석성 제목"                "주가·시황 기사 제외(사유 기록)"
need foreign.py    "본문 접근 불가"                       "유료벽 기사는 본문이 읽힐 때만(못 읽으면 사유와 함께 기록)"
need foreign.py    "같은 사건(요약 유사)"                 "요약 겹침 2차 중복"
need summarizer.py "_has_term"                            "영문 별칭은 단어 경계로 매칭(HSBC 등)"
need foreign.py    "valid_title_ko"                       "제목 번역 검증(원제목에 없던 영문 고유명사·거절문 차단)"
need foreign.py    "age_problem"                          "해외 게재일 필터(RSS 기간 옵션은 무시됨 — 1년 전 기사 유입 사고)"
need config.yaml   "deal_title"                           "은행이 투자자·주선자인 자금조달 기사 제외"
need foreign.py    "DROPPED_PER_REASON"                   "제외 목록은 사유별로 자르고 건수 집계는 전부(상한이 기록을 막지 않게)"
need html_generator.py "f-link"                           "국내 페이지는 해외 페이지로 링크만(파일 분리)"
deny html_generator.py "import foreign"                   "국내 렌더링이 해외 모듈에 의존하지 않음"
need .github/workflows/run.yml "outlets.json" "언론사 이름 파일 커밋 대상"
need archive.py    "backfill_press"       "영구 보관 CSV의 빈 매체 칸을 언론사 이름으로 채움"

need config.yaml   "min_line_chars: 14"   "본문 줄 기준 완화"
need summarizer.py "LAST_GROUND_RATIO"    "환각 판정 비율 진단"
need classifier.py "ALIAS_TO_FULL"        "축약형 회사명 분류 매핑"
deny html_generator.py "<h4>반영 %d건"     "검수목록에 반영 섹션 없음"

need html_generator.py "미반영 · %s"        "미반영 대표도 사유와 함께 노출"

echo "────────────────────────────────────────────"
# 문법 검사
for f in *.py; do
  python3 -m py_compile "$f" 2>/dev/null || { echo "  ✗ 문법 오류: $f"; fail=1; }
done
[ $fail -eq 0 ] && echo "  ✓ 전체 문법 정상"

echo
if [ $fail -eq 0 ]; then
  echo "통과 — push 해도 됩니다"
else
  echo "실패 — 위 항목을 고친 뒤 다시 실행하세요"
fi
exit $fail
