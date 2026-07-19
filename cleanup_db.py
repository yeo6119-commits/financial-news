"""DB 정리 — 기존 기사에 '현재 필터'를 다시 적용해 garbage·중복 제거

필터를 여러 번 개선하는 동안, 옛 필터로 통과한 기사들이 DB에 남아 있다.
증권사 리포트, 종합 브리핑, CSR 기사 등이 섞여 있고 같은 사건이 중복 적재돼 있다.

재수집 대신 이 방식을 쓰는 이유:
  · 재수집하면 요약 캐시가 사라져 전부 다시 요약 → 하루 쿼터의 3~4배 소요
  · 정리는 제목만으로 판정 → Groq 토큰 0, 네이버 API 0
  · 기존 요약을 그대로 보존

사용:
    python cleanup_db.py            # 미리보기 (아무것도 안 지움)
    python cleanup_db.py --apply    # 실제 정리
"""
import sqlite3
import sys
from collections import Counter

import yaml

import db as dbm
import deduplicator as d
import filter as f


def analyze(conn, cfg):
    comp = f.company_keywords(cfg)
    rel = f.relevance_keywords(cfg)
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM articles WHERE delivered=1").fetchall()]

    # 1) 현재 필터를 제목에 재적용
    garbage, keep = [], []
    for r in rows:
        a = f.prescreen({"title": r["title"]}, cfg, comp, rel)
        if a["excluded"]:
            r["_why"] = a["exclude_reason"]
            garbage.append(r)
        else:
            keep.append(r)

    # 2) 남은 것들 중 같은 사건 묶기
    for r in keep:
        r["norm_title"] = d.normalize_title(r["title"], cfg)
        r["_tokens"] = d.title_tokens(r["norm_title"])

    thr = cfg["dedup"]["title_similarity_threshold"]
    groups, used = [], set()
    for i, a in enumerate(keep):
        if i in used:
            continue
        g, used_now = [a], {i}
        for j in range(i + 1, len(keep)):
            if j in used:
                continue
            b = keep[j]
            same_day = (a["pub_date"] or "")[:10] == (b["pub_date"] or "")[:10]
            ov = d.token_overlap(a["_tokens"], b["_tokens"])
            ts = d.title_sim(a["norm_title"], b["norm_title"])
            if (same_day and ov >= 0.35) or ov >= 0.5 or ts >= thr:
                g.append(b)
                used_now.add(j)
        used |= used_now
        if len(g) > 1:
            groups.append(g)

    # 3) 각 그룹에서 대표 하나만 남긴다
    #    요약이 있는 것 > 제목이 구체적인 것(긴 것) 순
    dups = []
    for g in groups:
        g.sort(key=lambda x: (x.get("summary_ok") or 0, len(x["title"] or "")),
               reverse=True)
        for x in g[1:]:
            x["_rep"] = g[0]["title"]
            dups.append(x)

    return rows, garbage, groups, dups


def main():
    apply = "--apply" in sys.argv
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    conn = dbm.connect(cfg["db"]["path"])
    conn.row_factory = sqlite3.Row

    rows, garbage, groups, dups = analyze(conn, cfg)
    final = len(rows) - len(garbage) - len(dups)

    print("=" * 58)
    print(f"  현재 {len(rows)}건 → 정리 후 {final}건")
    print("=" * 58)

    print(f"\n[1] 현재 필터에 안 맞는 기사 {len(garbage)}건")
    for reason, n in Counter(g["_why"].split("(")[0] for g in garbage).most_common():
        print(f"      {reason:<12} {n:>3}건")
    for g in garbage[:6]:
        print(f"      · {g['title'][:50]}")
        print(f"          → {g['_why'][:50]}")
    if len(garbage) > 6:
        print(f"      ... 외 {len(garbage)-6}건")

    print(f"\n[2] 중복 {len(dups)}건 → {len(groups)}개 사건으로 통합")
    for g in sorted(groups, key=len, reverse=True)[:4]:
        print(f"      [{len(g)}건] {g[0]['title'][:46]}")
        for x in g[1:3]:
            print(f"            └ {x['title'][:44]}")
    if len(groups) > 4:
        print(f"      ... 외 {len(groups)-4}개 사건")

    if not apply:
        print("\n" + "=" * 58)
        print("  미리보기입니다. 실제로 지우려면:")
        print("      python cleanup_db.py --apply")
        print("=" * 58)
        return

    ids = [g["id"] for g in garbage] + [x["id"] for x in dups]
    conn.executemany("DELETE FROM articles WHERE id=?", [(i,) for i in ids])
    conn.commit()

    # VACUUM은 트랜잭션 밖에서 (db.py cleanup과 동일한 이유)
    conn.isolation_level = None
    conn.execute("VACUUM")
    conn.isolation_level = ""

    left = conn.execute("SELECT COUNT(*) FROM articles WHERE delivered=1").fetchone()[0]
    print(f"\n  {len(ids)}건 삭제 완료 → 현재 {left}건")
    print("\n  다음 순서:")
    print("      python rerender.py          # HTML 다시 생성")
    print("      python list_view.py         # 목록 다시 생성")
    print("      git add -f news.db output/  # DB는 gitignore라 -f 필요")
    print('      git commit -m "DB 정리: 옛 필터 통과분·중복 제거" && git push')


if __name__ == "__main__":
    main()
