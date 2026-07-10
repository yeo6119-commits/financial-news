# 금융 디지털·AI 뉴스 수집 시스템 v2.3

## 맥북 첫 실행 (5단계)
1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. 네이버 API 키 발급: developers.naver.com → 애플리케이션 등록 → 검색 API
4. Groq 키 발급: console.groq.com → API Keys
5. `.env` 파일 작성 후 `python main.py`

## .env 형식
```
NAVER_CLIENT_ID=발급받은ID
NAVER_CLIENT_SECRET=발급받은Secret
GROQ_API_KEY=발급받은키
```

## 결과 확인
`output/financial_news_archive.html` 을 브라우저로 열기.
매 실행마다 60일치 전체가 재생성됨 (회사 탭 + 회차 타임라인).

## 첫 실행 후 확인할 것 (튜닝 포인트)
- 수지 라인: 수집 = 반영 + 제외 합계가 맞는지
- 절단 키워드: 뜨면 해당 키워드 검색량 과다 → 키워드 분리 검토
- PR 어댑터 실패: 신한은 405 이슈로 실패 예상 → 개발자도구로 요청 방식 확인 후 press_collector.py의 shinhan() 수정
- 토스 노이즈율: 제외 목록에서 무관 비율 확인
- 본문 추출 실패 언론사: extractor.py의 GENERIC_BODY_SELECTORS에 셀렉터 추가

## 파일 구조
config.yaml(설정) / db.py(스키마·트랜잭션) / collector.py(네이버 수집)
press_collector.py(보도자료 9개 어댑터) / extractor.py(본문) / filter.py(필터)
deduplicator.py(중복) / classifier.py(분류) / summarizer.py(Groq 요약)
html_generator.py(아카이브 렌더) / main.py(파이프라인)

상세 사양: spec_v2.3_final.md 참조
