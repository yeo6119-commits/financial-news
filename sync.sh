#!/bin/bash
# 다운로드한 파일을 프로젝트로 옮기고, 회귀 검사 후 push
# 사용: ./sync.sh "커밋 메시지"
set -e
cd "$(dirname "$0")"
DL="$HOME/Downloads"
MSG="${1:-업데이트}"

echo "1. 다운로드 폴더에서 최신 파일 가져오기"
moved=0
for f in *.py *.yaml *.sh; do
  [ -f "$f" ] || continue
  # "filter.py", "filter (1).py", "filter (2).py" 중 가장 최근 것
  newest=$(ls -t "$DL/${f%.*}"*."${f##*.}" 2>/dev/null | head -1) || true
  if [ -n "$newest" ] && [ "$newest" -nt "$f" ]; then
    mv "$newest" "$f"
    echo "   ← $(basename "$newest")"
    moved=$((moved+1))
  fi
done
# docs 폴더
if [ -d "$DL/docs" ]; then
  mkdir -p docs && mv "$DL/docs"/*.md docs/ 2>/dev/null && rmdir "$DL/docs" 2>/dev/null || true
  echo "   ← docs/"
  moved=$((moved+1))
fi
[ $moved -eq 0 ] && echo "   (가져올 새 파일 없음)"

echo
echo "2. 회귀 검사"
bash check.sh || { echo; echo "검사 실패 — push 중단"; exit 1; }

echo "3. 변경 내용"
git add -A
git diff --cached --stat | tail -8
if git diff --cached --quiet; then
  echo "   변경 없음 — 종료"
  exit 0
fi

echo
read -p "push 할까요? [y/N] " ok
[ "$ok" = "y" ] || { echo "취소"; exit 0; }

git pull --no-edit && git commit -m "$MSG" && git push
echo
echo "완료. 아이폰 또는 페이지의 [실행] 버튼으로 돌리세요."
