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
# 단독 사용 시 일반 은행업무를 통과시킨 이력 (계좌 여세요 이벤트 → '계좌개설')
deny filter.py     '"계좌개설",'           "BODY_CORE에 '계좌개설' 단독 없음"
deny filter.py     '"결제", "QR"'          "BODY_CORE에 '결제' 단독 없음"

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
