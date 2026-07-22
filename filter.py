# =============================================================
# filter.py — 제외 판별 (v2.4)
# 변경점 (첫 실행 실측 반영):
#   1) prescreen(): 본문 추출 '전에' 제목만으로 1차 스크리닝
#      → 추출 대상 2,200건 → 200건 수준, 실행시간 30분 → 3분
#   2) 관련성 판정은 제목 + 본문 앞 800자에서만 탐색
#      → 푸터·관련기사·광고 오염으로 인한 무관 기사 통과 차단
#   3) 묶음/큐레이션 기사([여전사 풍향계] 등) 제외
# 원칙: 제외는 삭제가 아니라 표시. 사유를 반드시 남긴다.
# =============================================================
import re

# 여러 소식을 묶은 큐레이션 기사 — 단일 주체가 없어 3줄 요약 불가
BUNDLE_PATTERNS = [
    r"^\[.{0,10}(브리핑|풍향계|이모저모|24시|톡톡|NOW|픽|소식|동향|종합|단신|레이더)\]",
    r"^\[(오늘의|데일리|주간|금융|증권|보험|카드|여신)",
    r"外\s*$",
    r"\.\.\.\s*外",
    r"…\s*外",
]

# 제목에 이게 있으면 금융사 언급이 있어도 무관 (업종 무관 기사)
TITLE_NOISE = [
    # 업종 무관
    "홈쇼핑", "면세점", "게임", "교회", "목사", "안경", "복날", "여행객",
    "부동산시장", "임상", "어닝 서프라이즈", "Book Review",
    # 퀴즈·이벤트·정답 안내 (앱테크성 기사)
    "퀴즈", "정답", "앱테크", "행운적금", "감사 이벤트", "출석체크",
    "룰렛", "당첨자", "경품", "리워드 지급",
    # 스포츠 대회 후원 (삼성화재배 바둑 등)
    "바둑", "해설", "배 ", "대회", "우승", "출정식",
    # 사진·인사말 기사
    "인사말하는", "기념촬영", "포토뉴스",
]

# 제목이 이 패턴이면 제외 (정규식)
TITLE_NOISE_PATTERNS = [
    r"\d+월\s*\d+일\s*(오늘의|정답)",   # "7월 9일 오늘의 퀴즈 정답"
    r"정답\s*공개",
    r"^\[N잡",
    r"^\[.{0,6}배\s",                    # [삼성화재배 ...
]


def _hit(text: str, keywords: list) -> list:
    return [k for k in keywords if k in text]


def _dedup_companies(hits: list) -> list:
    """부분문자열 관계인 회사명을 하나로 취급.
    예: ['KB금융', 'KB국민은행'] 중 짧은 쪽이 긴 쪽에 포함되면 1개로 셈."""
    out = []
    for h in sorted(hits, key=len, reverse=True):
        if not any(h in o for o in out):
            out.append(h)
    return out


def company_keywords(cfg: dict) -> list:
    """config의 모든 회사·브랜드명 (제목 매칭용)"""
    out = []
    for g in cfg["tier1"].values():
        for companies in g.get("companies", {}).values():
            out += companies
        out += g.get("brands_standalone", [])
        out += g.get("group_keywords", [])
    for g in cfg["tier2"].values():
        for companies in g.get("subgroups", {}).values():
            out += companies
        out += g.get("brands_standalone", [])
    for names in cfg["overseas"]["subgroups"].values():
        out += names
    return list(dict.fromkeys(out))


# 제목에 나타나는 디지털·금융서비스 신호 (검색어가 아닌 판정 전용)
EXTRA_RELEVANCE = [
    # 디지털 자산·인프라 — 그 자체로 디지털/핀테크 사안임이 명확한 것만
    "스테이블코인", "블록체인", "디지털자산", "가상자산", "토큰", "정산", "실증",
    "PoC", "기술검증", "오픈뱅킹",
    # 시스템·조직 — "디지털"/"AI"와 결합해야 의미 있는 일반어는 제외
    #   (제외됨: 시스템·데이터·구축·고도화·제휴·협약·MOU·선정·전산
    #    → 대출상품·MOU·기탁 등 일반 기사에도 흔해 오탐의 주 원인이었음)
    "거버넌스", "클라우드",
    "이상거래", "신용평가모형", "자동화", "무인점포", "비대면",
    # 채널·UX — 디지털 채널임이 제목만으로 분명한 것
    "뱅킹앱", "MTS", "HTS", "간편인증", "메타버스", "슈퍼앱",
]

# 애널리스트 리포트/투자의견 — 회사명이 있어도 무조건 제외 (디지털·AI 이니셔티브 아님)
# 외국계 IB·기관의 시황·전망 코멘트 — 종목 리포트와 같은 성격
#   "모건스탠리 '연준보다 AI 지출이 문제'", "스탠다드차타드가 전망한 암호화폐 4종"
FORECAST_HOUSES = ["모건스탠리", "골드만삭스", "JP모건", "뱅크오브아메리카", "BofA",
                   "씨티", "웰스파고", "스탠다드차타드", "SC", "노무라", "UBS",
                   "도이체방크", "바클레이스", "HSBC", "번스타인", "웨드부시"]
FORECAST_WORDS = ["전망", "예상", "예측", "경고", "제시", "지목", "꼽았", "분석",
                  "진단", "평가절하", "목표", "추천", "수익 안겨", "문제", "우려",
                  "리스크", "주목", "선호", "매력", "부담", "기회", "위험"]

STOCK_REPORT_PATTERNS = [
    # 애널리스트 리포트·투자의견
    "목표가", "목표주가", "컨센서스", "투자의견", "매수의견", "매도의견",
    "실적 전망", "실적전망", "주가 조정", "저평가", "고평가", "적정주가",
    "애널리포트", "주목할 종목", "특징주", "종목진단", "이 주의 종목",
    # 시황·주가
    "주가", "은행주", "금융주", "증권주", "증시", "상한가", "하한가",
    "신고가", "52주", "시총", "코스피", "코스닥", "지분 확대", "외인 지분",
    "액면분할", "공매도", "배당수익률",
    # 투자 정보·시장 전망 (디지털·AI 이니셔티브가 아니라 투자 콘텐츠)
    "투자 노하우", "투자노하우", "고점", "저점", "레버리지", "조정 국면",
    "약세장", "강세장", "포트폴리오 전략", "자산배분 전략",
]

# 투자·증시 코너 태그 — [투자 노하우], [머니 톡] 등
INVEST_TAG_RE = re.compile(r"^\s*\[(투자|머니|재테크|증시|마켓|스탁|stock|주식)", re.I)
# 크립토·코인 시황 코너 — [크립토브리핑] 등
CRYPTO_COLUMN_RE = re.compile(
    r"\[(크립토|코인|블록체인|가상자산|디지털자산)\s*(브리핑|브리프|리포트|나우|투데이|위클리|칼럼)", re.I)
# 규제·수상·시황 — 회사명 일부('KB금융그룹')와 겹치므로 구절로 정확히 매칭.
#   관련성(AI·디지털)이 없을 때만 적용해 정상 기사 오차단 방지.
#   ※ '금융그룹 시대'는 제외하지 않는다 (사용자 요청: 해당 기사는 노출).
HARD_EXCLUDE_RE = re.compile(
    # 규제·지정·내부통제 (제도 이슈, 개별사 디지털 사안 아님)
    r"금융그룹\s*지정|빅테크\s*.{0,4}지정|내부통제\s*관건|지주.{0,4}지정|"
    r"동일인\s*지정|규제\s*대상\s*지정|"
    r"\d+년?\s*연속\s*(선정|수상)|수탁기관|어워드|시상식|관심도\s*\d*위|"           # 수상·순위
    r"소비자\s*관심도|최우수\s*(은행|기관|기업)|베스트\s*(뱅크|은행)|"
    r"거래대금|거래량\s*감소|시장\s*침체|'?한겨울'?|"                                 # 시황
    r"세미나|설명회|포럼\s*개최|회고전|전시회|미술관|갤러리")                          # 세미나·전시

# 증권사가 '다른 종목'을 평가하는 리포트 형식
#   예: 하나증권 "삼미금속, AI 데이터센터 전력 인프라 공급망 진입"
#   (증권사명 바로 뒤에 따옴표로 시작하는 분석 인용)
STOCK_REPORT_RE = re.compile(r'(증권|금융투자)\s*[,]?\s*["\u201c\u2018\']')

# 인사·부고·동정 — 디지털·AI 사안 아님
#   '인사'는 '인사이트', '인사말'에도 들어가므로 대괄호 태그/명시 표현만 매칭
PERSONNEL_RE = re.compile(
    r"^\[(인사|부고|동정|화촉|승진)\]|\[인사\]|임원\s?인사|정기\s?인사|인사\s?발령|"
    r"승진\s?인사|^\[신임\]|부고\s?:|"
    # 자연어 인사 (관련성보다 먼저 걸러 'AI 석학 수혈' 같은 인사 기사 제외)
    r"사외이사|사내이사|석학['\s]*수혈|이사회['\s]*.{0,8}(수혈|영입|합류|선임)|"
    r"신임\s*(대표|행장|사장|회장|부사장)|대표\s*내정|CEO\s*내정")

# 여러 회사를 나열한 종합 기사 — 태그 + 구분자 3개 이상
#   예: [주목! e금융] 하나·신한은행·케이뱅크·KB국민·IBK기업...
#       [여의도단신] 키움증권·미래에셋자산운용·한국투자신탁운용·KB자산운용
#   태그 이름은 매체마다 계속 새로 생기므로 이름 열거 대신 구조로 판정
TAG_RE = re.compile(r"^\s*[\[\【]")
SEP_RE = re.compile(r"[·ㆍ／/]")


# 본문 판정 전용 — 제목에 단서가 없을 때 '이 기사가 디지털·AI 사안인가'를 가름.
# 관련성 목록 전체(앱 이름·브랜드 포함)를 쓰면 CSR 기사에 "하나원큐로 신청" 한 줄만
# 스쳐도 통과되므로, 주제어급 키워드만 사용한다.
# 제목에 디지털·AI 단서가 없고 아래 주제에 해당하면 본문을 읽지 않고 제외.
# (본문 추출은 건당 1~6초가 들므로, 확인해봐야 소용없는 건 미리 걸러 시간을 아낀다)
NON_DIGITAL_TOPICS = [
    # 사회공헌·봉사
    "나눔", "봉사", "기탁", "후원", "성금", "헌혈", "김장", "연탄", "장학",
    "사회공헌", "기부", "삼계탕", "취약계층", "결연", "위문", "온기", "사랑의",
    "무더위", "한파", "명절", "다문화", "복지관", "요양원", "보육원",
    # 금리·상품
    "금리", "예금", "적금", "특판", "청약", "환율 우대", "수수료 면제",
    "대출 상품", "보험료", "연금 상품",
    # 실적·재무
    "순이익", "영업이익", "당기순", "실적 발표", "분기 실적", "결산",
    "배당", "자사주", "유상증자", "회사채",
    # 프로모션·이벤트 — 채널이 앱이어도 마케팅이지 디지털 사안이 아님
    #   (제목에 디지털 키워드가 있으면 앞 단계에서 이미 통과하므로 여기 걸리지 않음)
    "이벤트", "캐시백", "지원금", "경품", "사은품", "추첨", "응모", "쿠폰",
    "혜택 제공", "무료 제공", "할인",
    # 사고·분쟁·조직 이슈 — 회사 뉴스지만 디지털 사안이 아님
    "금융사고", "횡령", "배임", "노조", "파업", "합병론", "인수합병", "매각설",
    "소송", "손해배상", "국정감사", "국감",
    # 행사·조직
    "개점", "지점 신설", "점포 이전", "채용", "공모전", "위촉", "임명",
    "간담회", "협의회", "총회", "창립", "시무식", "종무식", "체육대회",
    "골프대회", "마라톤", "음악회", "전시회", "후원 협약",
]

BODY_CORE = [
    "AI", "인공지능", "생성형", "LLM", "머신러닝", "딥러닝", "챗봇", "GPT",
    "에이전트", "디지털", "DT", "DX", "플랫폼", "빅데이터", "데이터 분석",
    "클라우드", "블록체인", "스테이블코인", "가상자산", "디지털자산", "토큰화",
    "핀테크", "오픈뱅킹", "API", "자동화", "무인", "비대면", "온라인", "모바일앱",
    # 결제·채널 인프라 — 디지털 맥락이 분명한 것만.
    #   '결제'·'송금'·'계좌개설' 단독은 일반 은행 업무에도 쓰여 오탐을 부른다.
    #   ("계좌 여세요 이벤트"가 '계좌개설'로 통과한 사고)
    "QR결제", "QR 결제", "간편결제", "간편송금", "페이먼트", "선불충전",
    "결제 단말기", "POS", "NFC", "태그 결제", "결제 플랫폼", "결제 시스템",
    # 계좌·거래 인프라 — 고유 개념만
    "통합계좌", "옴니버스", "비대면 계좌", "온라인 계좌", "계좌 연동",
    "시스템 구축", "고도화", "전산", "IT", "테크", "알고리즘", "로보어드바이저",
    "메타버스", "슈퍼앱", "MTS", "간편결제", "간편송금", "이상거래탐지", "FDS",
]


def body_core_keywords(cfg: dict) -> list:
    return list(dict.fromkeys(BODY_CORE + cfg["classification"]["ai_keywords"]))


# 우리 대상이 아닌 회사 — 회사명에 부분 매칭되지만 금융사가 아님.
#   '토스'가 "앱토스랩스"에, 다른 키워드가 크립토 업체에 오매칭되는 것 차단.
NOT_OUR_COMPANY = ["앱토스", "앱토스랩스", "리플", "서클", "테더", "체이널리시스",
                   "코인베이스", "바이낸스", "크라켄", "점프트레이딩"]

# 핀테크사라도 이 주제는 디지털 사안이 아님 (M&A·실적·채용)
# 관련성 키워드('디지털'·'확대' 등)보다 먼저 걸러야 하는 강한 제외 주제.
#   제목에 '디지털'·'AI'가 있어도 이 맥락이면 디지털 사안이 아니다.
HARD_EXCLUDE = [
    # 채용
    "채용", "인턴 모집", "채용연계", "경력직", "신입 모집", "공채",
    "인재 확보", "인재 모집", "채용 설명회", "수시 모집",
    # 프로모션·제휴 혜택
    "할인", "캐시백", "적립 이벤트", "사전예약", "휴가철", "여행 할인",
    "제휴 혜택", "혜택 확대", "경품", "사은품", "무이자 할부", "맞춤 혜택",
    "캠페인", "이벤트 실시", "이벤트 진행", "특판", "포인트 제공", "쏜다",
    "정조준", "증정", "주식 증정", "상당 지급",   # 마케팅 특화어
    # 교육·예방 행사 (금융교육·예방교육은 CSR성 행사)
    "예방교육", "예방 교육", "금융교육", "금융 교육", "학교 예방",
    # 금융상품 (자산운용·수신·투자 상품)
    "펀드", "신탁", "RP 출시", "특판 RP", "ELS", "DLS", "ELB", "발행어음",
    "랩 서비스", "랩어카운트", "연금 상담", "상담하세요",
    # 카드·상품 라인업
    "카드 라인업", "라인업", "카드 출시", "신상품 출시",
    # 오프라인 점포·센터·거점
    "프라이빗 뱅킹", "PB센터", "PB 센터", "센터 개설", "센터 오픈", "지점 개설",
    "지점 신설", "점포", "영업점 개설", "거점 확대", "지점 확대",
    # 교육·행사 프로그램
    "프로그램 개설", "기 개설", "아카데미", "교육 프로그램", "연수 프로그램",
    "인사이트 프로그램", "글로벌 인사이트",
    # 순위·평판 (HARD_EXCLUDE_RE 보강)
    "브랜드평판", "브랜드 평판", "평판 1위",
]

# 보이스피싱 '미담' — FDS·이상거래탐지 같은 디지털 대응이 아니라
#   창구 직원이 눈치채고 막은 미담. 제목에 '보이스피싱'이 있어도 제외.
PHISHING_ANECDOTE = re.compile(
    r"(막은|막아|차단|지켜|지킨|예방)\s*(공로|미담)?|감사장|표창|의인|"
    r"직원.{0,8}(막|지키|눈치)|계장|출동|수상")

FINTECH_EXCLUDE = ["인수", "매각", "합병", "품은", "지분 취득", "대환대출",
                   "돌파", "순이익", "영업이익", "실적", "분기", "최대 실적",
                   "채용", "인재 찾", "사람 찾", "경력직", "공채"]


def fintech_companies(cfg: dict) -> set:
    """인터넷은행·핀테크사 — 사업 자체가 디지털이므로 본문 확인을 면제한다.

    은행의 삼계탕 나눔 기사는 디지털이 아니지만,
    네이버파이낸셜의 금감원 제재 기사는 그 자체로 핀테크 뉴스다.
    회사 성격에 따라 판정 기준이 달라야 한다.
    """
    out = set()
    g = cfg["tier1"].get("인터넷은행핀테크", {})
    for names in g.get("companies", {}).values():
        out.update(names)
    out.update(g.get("brands_standalone", []))
    return out


def relevance_keywords(cfg: dict) -> list:
    """관련성 키워드 = 검색어 + 로컬 + AI + 보안 + 추가어 + 앱/서비스 브랜드명

    앱·서비스 브랜드명(SOL LINK, 하나원큐, KB Pay...)이 제목에 있으면
    그 자체로 디지털 서비스 기사이므로 관련성 키워드로 취급한다.
    classifier의 BRAND_TO_COMPANY를 재사용해 매핑을 한 곳에서 관리."""
    from classifier import BRAND_TO_COMPANY
    return list(dict.fromkeys(
        cfg["search_service_keywords"]
        + cfg["local_relevance_keywords"]
        + cfg["classification"]["ai_keywords"]
        + cfg["filters"]["security_override"]
        + EXTRA_RELEVANCE
        + list(BRAND_TO_COMPANY.keys())))


# ----------------------------------------------------------
# 1차 스크리닝 — 본문 추출 '전' 호출 (제목만 사용)
# ----------------------------------------------------------
def _policy_screen(article: dict, cfg: dict) -> dict:
    """정책·규제 기사 전용 판정 — 회사명 불필요, 디지털·AI 맥락만 확인.

    금융당국의 제도·규제 기사는 회사명이 없어 일반 필터를 못 통과한다.
    대신 '정책 키워드 + 디지털 맥락'이 함께 있는지로 판정한다.
    """
    title = article.get("title", "")
    ps = cfg["policy_section"]

    # 종합기사·시황 코너는 정책 섹션에서도 배제
    if TAG_RE.match(title) and len(SEP_RE.findall(title)) >= 3:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(종합기사)"
        return article
    if CRYPTO_COLUMN_RE.search(title) or INVEST_TAG_RE.match(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(시황 코너)"
        return article

    # 디지털·AI 맥락이 제목에 있으면 통과, 없으면 즉시 제외.
    #   정책 기사는 물량이 많아 '본문 확인'을 열면 extractor가 폭증한다.
    #   검색어 자체가 정책 키워드이므로, 제목에 맥락이 없으면 대개 무관 기사.
    if _hit(title, ps["digital_context"]):
        article["excluded"] = 0
        article["exclude_reason"] = None
        article["_needs_body_check"] = False
        return article
    article["excluded"] = 1
    article["exclude_reason"] = "무관(정책이나 제목에 디지털 맥락 없음)"
    return article


def prescreen(article: dict, cfg: dict, companies: list, relevance: list) -> dict:
    title = article.get("title", "")
    f = cfg["filters"]

    # 정책·규제 기사는 전용 판정 (회사명 불필요). enabled일 때만.
    _ps = cfg.get("policy_section", {})
    if _ps.get("enabled") and article.get("menu_id") == _ps.get("menu_id"):
        return _policy_screen(article, cfg)

    # (0) 애널리스트 리포트·시황 — 회사명이 있어도 종목 분석일 뿐 디지털·AI 사안 아님
    for pat in STOCK_REPORT_PATTERNS:
        if pat in title:
            article["excluded"] = 1
            article["exclude_reason"] = f"무관(주식·리포트: {pat})"
            return article
    if STOCK_REPORT_RE.search(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(증권사 종목 리포트)"
        return article
    if INVEST_TAG_RE.match(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(투자·증시 코너)"
        return article
    if CRYPTO_COLUMN_RE.search(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(크립토 시황 코너)"
        return article
    # 외국계 IB의 시황 전망 — 회사명 + 전망 동사가 함께 있으면 종목 리포트급
    if _hit(title, FORECAST_HOUSES) and _hit(title, FORECAST_WORDS):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(기관 시황 전망)"
        return article

    # (0-b) 인사·부고
    if PERSONNEL_RE.search(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(인사·부고)"
        return article

    # (0-c) 태그 + 구분자 3개 이상 나열 → 종합 기사
    #       (회사명이 '하나', 'KB국민'처럼 잘려 매칭이 안 되는 경우까지 잡음)
    if TAG_RE.match(title) and len(SEP_RE.findall(title)) >= 3:
        article["excluded"] = 1
        article["exclude_reason"] = "종합기사(여러 건 나열)"
        return article

    # (1) 묶음/종합 기사
    #  - 회사명이 하나도 없으면: 주체 불명 → 제외
    #  - 회사명이 3곳 이상 나열되면: 여러 소식 종합 기사 → 제외
    #    예: [오늘의 은행] KB국민은행·신한은행·하나은행·IBK기업은행·BNK경남은행
    #        [금융레이더] 농협생명/KB국민카드/현대카드/IBK저축은행
    #  - 회사명이 1~2곳이면: 단일 주제일 수 있으므로 통과
    #    예: [뉴스워커_하나카드] 판다 디자인 트래블로그 → 하나카드 단일 기사
    comp_in_title = _hit(title, companies)
    for pat in BUNDLE_PATTERNS:
        if re.search(pat, title):
            if not comp_in_title:
                article["excluded"] = 1
                article["exclude_reason"] = "묶음기사(단일 주체 없음)"
                return article
            # 태그가 붙은 기사에서 회사가 2곳 이상 언급되면 종합/나열 기사
            # ([뉴스워커_하나카드] 처럼 단일 회사 코너물은 1곳이므로 통과)
            if len(_dedup_companies(comp_in_title)) >= 2:
                article["excluded"] = 1
                article["exclude_reason"] = (
                    "종합기사(%d개사 나열)" % len(_dedup_companies(comp_in_title)))
                return article
            break

    # 제목 태그가 없어도 회사명이 4곳 이상이면 종합 기사로 판단
    if len(_dedup_companies(comp_in_title)) >= 4:
        article["excluded"] = 1
        article["exclude_reason"] = (
            "종합기사(%d개사 나열)" % len(_dedup_companies(comp_in_title)))
        return article

    # (2) 업종 무관 노이즈
    noise = _hit(title, TITLE_NOISE)
    if noise:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(제목 노이즈: %s)" % noise[0]
        return article
    for pat in TITLE_NOISE_PATTERNS:
        if re.search(pat, title):
            article["excluded"] = 1
            article["exclude_reason"] = "무관(퀴즈·이벤트성 제목)"
            return article

    # (3) 스포츠 — 제목에 1개만 있어도 제외
    sports = _hit(title, f["sports_exclude"])
    if sports:
        article["excluded"] = 1
        article["exclude_reason"] = "스포츠(%s)" % sports[0]
        return article

    # (4) 범죄 — 보안 오버라이드 우선
    crime = _hit(title, f["crime_exclude"])
    security = _hit(title, f["security_override"])
    if crime and not security:
        article["excluded"] = 1
        article["exclude_reason"] = "범죄(%s)" % crime[0]
        return article

    # (5) 핵심: 제목에 회사·브랜드명이 반드시 있어야 함
    comp_hits = _hit(title, companies)
    if not comp_hits:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(제목에 대상 금융사 없음)"
        return article
    # 우리 대상이 아닌 회사가 오매칭된 경우 제외 ('토스'→"앱토스랩스").
    #   진짜 대상사도 함께 있으면 유지.
    not_ours = _hit(title, NOT_OUR_COMPANY)
    if not_ours:
        cleaned = title
        for n in not_ours:
            cleaned = cleaned.replace(n, "")
        if not _hit(cleaned, companies):
            article["excluded"] = 1
            article["exclude_reason"] = "무관(대상 아닌 업체: %s)" % not_ours[0]
            return article

    # 강한 제외 주제 — 관련성 단어('디지털'·'확대' 등)가 있어도 제외.
    #   "디지털 인재 채용", "혜택 확대", "제휴 할인"이 관련성에서 새던 문제.
    hard = _hit(title, HARD_EXCLUDE)
    if hard:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(%s)" % hard[0]
        return article
    # 보이스피싱 미담(직원이 막은 공로) — 디지털 대응이 아님
    if "보이스피싱" in title and PHISHING_ANECDOTE.search(title):
        article["excluded"] = 1
        article["exclude_reason"] = "무관(보이스피싱 예방 미담)"
        return article

    # (6) 제목에 서비스·AI·관련성 키워드가 있으면 즉시 통과.
    #     없으면 제외하지 않고 '본문 확인 대기'로 넘긴다.
    #     → 본문 추출 후 apply_filters()가 본문 앞부분을 읽어 최종 판정.
    #       (제목만으로는 디지털·AI 기사인지 알 수 없는 경우가 많기 때문)
    # 핀테크사의 M&A·실적·채용은 관련성 단어('출시' 등)가 있어도 제외.
    #   ("대환대출 1조 돌파"에 '출시'가 섞여 통과하던 문제)
    if set(comp_hits) & fintech_companies(cfg):
        fin_noise = _hit(title, FINTECH_EXCLUDE)
        if fin_noise:
            article["excluded"] = 1
            article["exclude_reason"] = "무관(%s)" % fin_noise[0]
            return article

    rel_hits = _hit(title, relevance)
    if rel_hits:
        article["excluded"] = 0
        article["exclude_reason"] = None
        article["_needs_body_check"] = False
        return article

    # 관련성 없음 → 규제·수상·시황·세미나면 제외 (회사명 겹침 없이 구절로 매칭)
    m = HARD_EXCLUDE_RE.search(title)
    if m:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(규제·수상·시황: %s)" % m.group()[:12]
        return article
    # 제목에 디지털·AI 단서가 없음 → 본문을 읽어볼 가치가 있는지 먼저 판단
    #   (핀테크사라도 봉사·기탁 기사는 여기서 걸러진다)
    topic = _hit(title, NON_DIGITAL_TOPICS)
    if topic:
        article["excluded"] = 1
        article["exclude_reason"] = "무관(%s 기사)" % topic[0]
        return article

    article["excluded"] = 0
    article["exclude_reason"] = None
    # 핀테크·인터넷은행은 사업 자체가 디지털 → 본문 확인 없이 통과.
    #   (M&A·실적·채용은 위에서 이미 걸렀다)
    if set(comp_hits) & fintech_companies(cfg):
        article["_needs_body_check"] = False
    else:
        article["_needs_body_check"] = True
    return article


# ----------------------------------------------------------
# 2차 필터 — 본문 확보 후 호출
# ----------------------------------------------------------
def apply_filters(article: dict, cfg: dict) -> dict:
    if article.get("excluded"):        # 1차에서 이미 제외됨
        return article

    f = cfg["filters"]
    title = article.get("title", "")
    body = article.get("body") or ""
    head = body[:800]                  # 본문 앞부분만 — 푸터·관련기사 오염 차단
    text = "%s %s" % (title, head)

    # 제목에 디지털·AI 키워드가 없던 건 → 본문으로 최종 판정
    #  · 리드(앞 400자)에서만 찾는다. 한국 기사는 역피라미드라 주제가 리드에 온다.
    #    뒤쪽에 스치듯 나오는 언급은 그 기사의 주제가 아니므로 근거로 삼지 않는다.
    #  · 핵심 키워드(BODY_CORE)만 인정. 앱 이름·일반어는 제외.
    if article.get("_needs_body_check"):
        if not body:
            article["excluded"] = 1
            article["exclude_reason"] = "무관(제목·본문에서 디지털·AI 근거 없음)"
            return article
        lead = body[:400]
        # 정책 기사는 디지털 맥락(digital_context)으로 판정
        if article.get("menu_id") == cfg.get("policy_section", {}).get("menu_id"):
            if _hit(lead, cfg["policy_section"]["digital_context"]):
                article["excluded"] = 0
                article["exclude_reason"] = None
            else:
                article["excluded"] = 1
                article["exclude_reason"] = "무관(정책이나 디지털·AI 아님)"
            return article
        core_hits = _hit(lead, body_core_keywords(cfg))
        if not core_hits:
            article["excluded"] = 1
            article["exclude_reason"] = "무관(본문 확인: 디지털·AI 내용 아님)"
            return article
        article["_body_relevance"] = core_hits[0]   # 본문 근거 기록

    security = _hit(text, f["security_override"])

    sports = _hit(text, f["sports_exclude"])
    if len(sports) >= 2:
        article["excluded"] = 1
        article["exclude_reason"] = "스포츠(%s)" % ",".join(sports[:2])
        return article

    crime = _hit(text, f["crime_exclude"])
    if crime and not security:
        article["excluded"] = 1
        article["exclude_reason"] = "범죄(%s)" % crime[0]
        return article

    promo = _hit(text, f["promo_exclude_hint"])
    substantive = _hit(text, cfg["local_relevance_keywords"]
                       + cfg["classification"]["ai_keywords"])
    if promo and not substantive:
        article["excluded"] = 1
        article["exclude_reason"] = "홍보성(%s)" % promo[0]
        return article

    article["excluded"] = 0
    article["exclude_reason"] = None
    return article
