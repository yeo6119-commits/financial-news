#!/bin/bash
# 회귀 검사 후 커밋·push
# 사용: ./sync.sh "커밋 메시지"
#
# 다운로드 폴더 자동 이동은 제거했다.
#   수정시각만으로는 어느 쪽이 최신 '내용'인지 알 수 없어,
#   구버전이 최신 파일을 덮어쓰는 사고가 있었다.
#   파일은 Finder에서 직접 끌어다 놓고, 이 스크립트는 검사·push만 한다.
set -e
cd "$(dirname "$0")"
MSG="${1:-업데이트}"

echo "1. 회귀 검사"
bash check.sh || { echo; echo "검사 실패 — push 중단"; exit 1; }

echo "2. 변경 내용"
git add -A
if git diff --cached --quiet; then
  echo "   변경 없음 — 종료"
  exit 0
fi
git diff --cached --stat | tail -10

echo
read -p "push 할까요? [y/N] " ok
[ "$ok" = "y" ] || { echo "취소 (git add 상태는 유지됨)"; exit 0; }

git pull --no-edit && git commit -m "$MSG" && git push
echo
echo "완료. 페이지의 [실행] 버튼으로 돌리세요."
