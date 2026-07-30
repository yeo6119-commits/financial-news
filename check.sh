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
need main.py       "review_many"          "검토 에이전트 파이프라인 연결"
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
need extractor.py  "attempt in range(2)" "접속실패 1회 재시도(간헐적 봇차단)"

need deduplicator.py "rep.get(\"_comp\") and a.get(\"_comp\")" "클러스터 합류시 대표와 회사공유 필수"
need deduplicator.py "body_ok"              "빈 본문 동일판정 차단"
need html_generator.py "len(m) > 3"         "중복목록 기사 링크"

need filter.py     "def is_roundup"        "묶음기사 제외(브리핑·단신·外)"

need .github/workflows/run.yml "pull --rebase" "push 충돌 재시도(실행 실패 방지)"
need config.yaml   "'플랫폼'·'비대면' 제거" "저생산 검색어 정리 유지"

need html_generator.py "rep-out"             "중복 대표 반영여부 배지"

need .github/workflows/run.yml "47 21"  "아침 정기실행(KST 06:47, 지연흡수)"
need .github/workflows/run.yml "13 23"  "백업 실행(KST 08:13)"

need html_generator.py "이 사건 자체를 검수 목록에서 뺀다" "미반영 대표 숨김"
need html_generator.py "seen-more"           "기열람 대표1건+더보기 접힘"
need html_generator.py "rep-dup"             "본문무관 반복사건 묶음"

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
