"""임계값 10 적용 후, 현재 DB 기사로 실제 클러스터링을 시뮬레이션."""
import sqlite3, yaml
import deduplicator as d

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
conn = sqlite3.connect(cfg["db"]["path"])
conn.row_factory = sqlite3.Row
rows = [dict(r) for r in conn.execute(
    """SELECT title, company, fin_group, sector, body_fingerprint, pub_date, press, body_hash
       FROM articles WHERE delivered=1
       ORDER BY fin_group, pub_date DESC""").fetchall()]

thr = cfg["dedup"]["title_similarity_threshold"]
for a in rows:
    a["norm_title"] = d.normalize_title(a["title"], cfg)
    a["_tokens"] = d.title_tokens(a["norm_title"])
    a["body"] = "x"  # 본문 있다고 가정 (fingerprint로 판정)

clusters = []
for a in rows:
    placed = False
    for cl in clusters:
        rep = cl[0]
        same_hash = a.get("body_hash") and a["body_hash"]==rep.get("body_hash")
        sim = d.title_sim(a["norm_title"], rep["norm_title"]) >= thr
        try:
            hb = d.hamming(int(a["body_fingerprint"],16), int(rep["body_fingerprint"],16)) <= 10
        except: hb = False
        ov = d.token_overlap(a["_tokens"], rep["_tokens"])
        ev = d.same_day(a, rep) and ov >= 0.42
        if same_hash or sim or hb or ev:
            cl.append(a); placed=True; break
    if not placed:
        clusters.append([a])

dups = [cl for cl in clusters if len(cl) > 1]
print(f"전체 {len(rows)}건 → 클러스터 {len(clusters)}개 (중복 묶음 {len(dups)}개)\n")
print("=== 묶인 중복 그룹 ===")
for cl in dups:
    print(f"\n[{len(cl)}건 묶임] 대표 남길 회사: {cl[0]['company']}")
    for a in cl:
        print(f"   · {a['title'][:45]}")

removed = sum(len(cl)-1 for cl in dups)
print(f"\n→ 중복 제거로 {removed}건 감소 ({len(rows)} → {len(rows)-removed}건)")
