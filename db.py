# =============================================================
# db.py — SQLite 스키마·트랜잭션 관리 (v2.2)
# 핵심 원칙:
#   1) delivered와 last_successful_run_at은 HTML 성공 후 단일 트랜잭션으로만 갱신
#   2) 본문 전문은 저장하지 않음 (해시·fingerprint만)
#   3) 60일 초과 데이터 자동 정리
# =============================================================
import sqlite3
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    norm_title TEXT NOT NULL,
    press TEXT,
    pub_date TEXT,                 -- ISO 8601 KST
    original_url TEXT,
    naver_url TEXT,
    url_hash TEXT NOT NULL,
    norm_title_hash TEXT NOT NULL,
    body_hash TEXT,
    body_fingerprint TEXT,         -- simhash hex
    fin_group TEXT,                -- menu_id (탭)
    subgroup TEXT,                 -- 세부 지주·회사군
    company TEXT,                  -- 기사 주체 회사명 (제목 기준 판정)
    sector TEXT,                   -- 은행/증권/카드/캐피탈/보험/저축은행/기타
    dig_ai TEXT,                   -- 디지털 | AI
    matched_keywords TEXT,         -- 쉼표 구분
    search_keyword TEXT,           -- 이 기사를 잡은 검색식
    summary TEXT,                  -- 3줄 요약 (\\n 구분)
    extract_ok INTEGER DEFAULT 0,
    summary_ok INTEGER DEFAULT 0,
    extract_fail_reason TEXT,
    summary_fail_reason TEXT,
    excluded INTEGER DEFAULT 0,
    exclude_reason TEXT,           -- 기간외/중복/스포츠/범죄/무관/기열람
    dup_of INTEGER,                -- 배치 내 중복 시 대표 기사 id
    delivered INTEGER DEFAULT 0,
    run_id INTEGER,                -- 수집 회차
    collected_at TEXT NOT NULL,
    delivered_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_url_hash ON articles(url_hash);
CREATE INDEX IF NOT EXISTS idx_title_hash ON articles(norm_title_hash);
CREATE INDEX IF NOT EXISTS idx_delivered ON articles(delivered);
CREATE INDEX IF NOT EXISTS idx_run ON articles(run_id);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_at TEXT NOT NULL,
    search_start TEXT NOT NULL,
    search_end TEXT NOT NULL,
    truncated_window INTEGER DEFAULT 0,   -- 72시간 상한으로 잘림 여부
    truncated_from TEXT,                  -- 잘린 구간 시작 (수동 재수집 안내용)
    api_calls INTEGER DEFAULT 0,
    keywords_used INTEGER DEFAULT 0,
    raw_collected INTEGER DEFAULT 0,
    cutoff_keywords TEXT,                 -- start=1000 절단 발생 키워드 (쉼표)
    status TEXT DEFAULT 'running',        -- running | success | failed
    finished_at TEXT
);
"""


def now_kst() -> datetime:
    return datetime.now(KST)


def connect(path: str = "news.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ----------------------------------------------------------
# 실행 회차 관리
# ----------------------------------------------------------
def get_last_successful_run(conn) -> datetime | None:
    row = conn.execute(
        "SELECT search_end FROM runs WHERE status='success' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return datetime.fromisoformat(row["search_end"]) if row else None


def start_run(conn, search_start, search_end, truncated=False, truncated_from=None) -> int:
    cur = conn.execute(
        "INSERT INTO runs (requested_at, search_start, search_end, truncated_window, truncated_from) "
        "VALUES (?,?,?,?,?)",
        (now_kst().isoformat(), search_start.isoformat(), search_end.isoformat(),
         int(truncated), truncated_from.isoformat() if truncated_from else None),
    )
    conn.commit()
    return cur.lastrowid


def update_run_stats(conn, run_id, **kwargs):
    sets = ", ".join(f"{k}=?" for k in kwargs)
    conn.execute(f"UPDATE runs SET {sets} WHERE id=?", (*kwargs.values(), run_id))
    conn.commit()


def fail_run(conn, run_id):
    conn.execute(
        "UPDATE runs SET status='failed', finished_at=? WHERE id=?",
        (now_kst().isoformat(), run_id),
    )
    conn.commit()


# ----------------------------------------------------------
# 기사 저장·조회
# ----------------------------------------------------------
def insert_article(conn, art: dict) -> int:
    cols = ", ".join(art.keys())
    ph = ", ".join("?" * len(art))
    cur = conn.execute(f"INSERT INTO articles ({cols}) VALUES ({ph})", tuple(art.values()))
    conn.commit()
    return cur.lastrowid


def url_or_title_delivered(conn, url_hash: str, norm_title_hash: str) -> bool:
    """과거 delivered 제외 — 완전 일치만 (후속 보도 보호)"""
    row = conn.execute(
        "SELECT 1 FROM articles WHERE delivered=1 AND (url_hash=? OR norm_title_hash=?) LIMIT 1",
        (url_hash, norm_title_hash),
    ).fetchone()
    return row is not None


def find_delivered_by_fingerprint(conn, fingerprint: str, days: int = 30):
    """과거 delivered 기사 중 본문 지문이 유사한 건 탐색 (A안: 재탕 기사 제외)
    simhash 해밍거리 비교는 호출측에서 수행 — 여기선 후보만 반환"""
    cutoff = (now_kst() - timedelta(days=days)).isoformat()
    return conn.execute(
        """SELECT id, title, body_fingerprint, pub_date FROM articles
           WHERE delivered=1 AND body_fingerprint IS NOT NULL
             AND body_fingerprint != '0' AND collected_at >= ?""",
        (cutoff,),
    ).fetchall()


def find_delivered_for_dedup(conn, days: int = 3):
    """최근 delivered 기사 (제목+지문) — 회차 간 재탕/동일사건 제외용.
    days를 짧게(3일) 잡아 오래된 기사와의 오인식을 방지."""
    cutoff = (now_kst() - timedelta(days=days)).isoformat()
    return conn.execute(
        """SELECT title, body_fingerprint FROM articles
           WHERE delivered=1 AND collected_at >= ?""",
        (cutoff,),
    ).fetchall()


def get_cached_summary(conn, url_hash: str):
    """C안: 이미 요약된 동일 URL 기사가 있으면 요약문 재사용 (Groq 호출 0회)"""
    row = conn.execute(
        """SELECT summary, dig_ai, fin_group, subgroup, company, sector, matched_keywords
           FROM articles WHERE url_hash=? AND summary_ok=1 LIMIT 1""",
        (url_hash,),
    ).fetchone()
    return row


def already_in_batch(conn, run_id: int, url_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM articles WHERE run_id=? AND url_hash=? LIMIT 1", (run_id, url_hash)
    ).fetchone()
    return row is not None


def get_archive_articles(conn, days: int = 60):
    """HTML 아카이브 렌더링용 — delivered 기사 전체 (회차 역순)"""
    cutoff = (now_kst() - timedelta(days=days)).isoformat()
    return conn.execute(
        """SELECT a.*, r.requested_at AS run_requested, r.search_start AS run_start, r.search_end AS run_end
           FROM articles a JOIN runs r ON a.run_id = r.id
           WHERE a.delivered=1 AND a.collected_at >= ?
           ORDER BY r.id DESC, a.fin_group, a.sector, a.company""",
        (cutoff,),
    ).fetchall()


def get_run_history(conn, days: int = 60):
    """회차별 요청 시각·반영 건수·요약 성공/실패 집계 (HTML 이력 패널용)"""
    cutoff = (now_kst() - timedelta(days=days)).isoformat()
    return conn.execute(
        """SELECT r.id, r.requested_at, r.search_start, r.search_end,
                  r.raw_collected, r.api_calls, r.status,
                  COUNT(CASE WHEN a.delivered=1 THEN 1 END) AS delivered_cnt,
                  COUNT(CASE WHEN a.delivered=1 AND a.summary_ok=1 THEN 1 END) AS summary_ok_cnt,
                  COUNT(CASE WHEN a.delivered=1 AND a.summary_ok=0 THEN 1 END) AS summary_fail_cnt
           FROM runs r LEFT JOIN articles a ON a.run_id = r.id
           WHERE r.requested_at >= ? AND r.status='success'
           GROUP BY r.id ORDER BY r.id DESC""",
        (cutoff,),
    ).fetchall()


def get_run_excluded(conn, run_id: int):
    return conn.execute(
        "SELECT * FROM articles WHERE run_id=? AND excluded=1", (run_id,)
    ).fetchall()


# ----------------------------------------------------------
# delivered 트랜잭션 — HTML 생성 성공 후에만 호출할 것
# ----------------------------------------------------------
def commit_delivered(conn, run_id: int, article_ids: list[int]):
    """HTML rename 성공 확인 후 단일 트랜잭션으로 delivered + run 성공 처리"""
    ts = now_kst().isoformat()
    try:
        conn.execute("BEGIN")
        conn.executemany(
            "UPDATE articles SET delivered=1, delivered_at=? WHERE id=?",
            [(ts, aid) for aid in article_ids],
        )
        conn.execute(
            "UPDATE runs SET status='success', finished_at=? WHERE id=?", (ts, run_id)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ----------------------------------------------------------
# 60일 정리
# ----------------------------------------------------------
def cleanup(conn, retention_days: int = 60, excluded_days: int = 14):
    """D안: 반영 기사는 60일, 제외 기사는 14일만 보관 (DB 비대화 방지)"""
    cutoff = (now_kst() - timedelta(days=retention_days)).isoformat()
    ex_cutoff = (now_kst() - timedelta(days=excluded_days)).isoformat()
    conn.execute("DELETE FROM articles WHERE collected_at < ?", (cutoff,))
    conn.execute("DELETE FROM articles WHERE excluded=1 AND collected_at < ?", (ex_cutoff,))
    conn.execute("DELETE FROM runs WHERE requested_at < ?", (cutoff,))
    conn.commit()
    conn.isolation_level = None
    conn.execute("VACUUM")
    conn.isolation_level = ""
    conn.commit()
