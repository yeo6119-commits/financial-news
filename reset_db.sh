#!/bin/bash
# 첫 실행 데이터 초기화 (필터 수정 후 재실행용)
rm -f news.db
rm -f output/financial_news_archive.html
echo "DB 및 HTML 초기화 완료. python main.py 실행하세요."
