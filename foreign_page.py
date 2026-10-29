# =============================================================
# foreign_page.py — 해외(영문) 기사 페이지 (output/foreign.html)
#
# 국내 페이지(financial_news_archive.html)와 파일이 완전히 따로다. 이 페이지는 해외 트랙 워크플로만
# 만들고 커밋하므로 국내 실행과 파일이 겹치지 않는다(rebase 충돌 없음). 국내 페이지에는 링크만 걸린다.
# 스타일·공유 팝업·'다른 매체' 팝업은 국내 페이지의 것을 그대로 쓴다.
# =============================================================
import html as H
import json
import os
import sys
from datetime import datetime

import foreign_store as store
import html_generator as hg

OUT_FILE = os.path.join("output", "foreign.html")
FEED_FILE = os.path.join("output", "foreign_feed.json")    # 국내 페이지가 열릴 때 읽어 국내 기사와 같은 목록에 끼워 넣는 데이터
DOMESTIC_PAGE = "financial_news_archive.html"
WEEK = "월화수목금토일"

EXTRA_CSS = """
.back{display:inline-block;font-size:12.5px;font-weight:700;color:var(--teal);text-decoration:none;
background:var(--teal-soft);border-radius:6px;padding:4px 12px;margin:4px 0 2px}
.back:hover{background:var(--teal);color:#fff}
.f-note{font-size:12px;color:var(--muted);margin:2px 0 10px;line-height:1.55}
.f-empty{font-size:13px;color:var(--muted);padding:26px 4px;line-height:1.7}
.drop-list{padding:0 14px 12px;max-height:360px;overflow-y:auto}
.ex-item a{color:inherit;text-decoration:none} .ex-item a:hover{text-decoration:underline}
details.excluded{margin-top:8px}
"""


def _day_label(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
        return "%s (%s)" % (day, WEEK[d.weekday()])
    except ValueError:
        return day


def _share_item(a: dict) -> dict:
    """국내 카드와 같은 공유 문구를 만들기 위한 형태 맞추기."""
    return {"pub_date": a.get("pub_date") or "", "summary": a.get("summary") or "",
            "original_url": a.get("url") or "", "naver_url": ""}


def _card(a: dict, sim: dict) -> str:
    cos = [a["company"]] + [c for c in a.get("also", []) if c != a["company"]]
    share = hg._share_text(_share_item(a), a["company"])
    copy_btn = ('<button type="button" class="copy-sum" title="공유용 요약 보기·복사" aria-label="요약 복사" '
                'data-copy="%s"></button>' % H.escape(share, quote=True).replace("\n", "&#10;"))
    lis = "".join("<li>%s</li>" % H.escape(l.lstrip("*-• ").strip())
                  for l in (a.get("summary") or "").splitlines() if l.strip())
    dups = a.get("dups") or []
    sim_btn = ""
    if dups:
        key = "f" + a["id"]
        sim[key] = [[d.get("press", ""), d.get("title", ""), d.get("url", ""), ""] for d in dups]
        sim_btn = ('<button type="button" class="sim-btn" data-sim="%s" data-n="%d" '
                   'title="같은 사건을 다룬 다른 매체 기사"></button>' % (key, len(dups)))
    also = ('<div class="also">함께 다룬 회사: %s</div>' % H.escape(", ".join(cos[1:]))) if len(cos) > 1 else ""
    pub = (a.get("pub_date") or "")[:16].replace("T", " ")
    url = H.escape(a.get("url") or "#")
    orig = '<div class="a-orig">%s</div>' % H.escape(a["title"]) if a.get("title_ko") else ""   # 번역 제목이 있으면 원문 제목은 작게
    return f"""
<div class="article has-sum" data-co="{H.escape(a['company'])}" data-cos="|{H.escape('|'.join(cos))}|">
 {copy_btn}
 <div class="tags"><span class="tag path">{H.escape(a['company'])} · 해외</span><span class="tag digital">영문 기사 번역 요약</span></div>
 <h3><a href="{url}" target="_blank" rel="noopener">{H.escape(a.get('title_ko') or a['title'])}</a></h3>{orig}
 <div class="a-meta">{H.escape(a.get('press') or '')} · {pub} KST</div>
 <ul class="summary">{lis}</ul>{also}
 <div class="card-actions"><a class="src-link" href="{url}" target="_blank" rel="noopener">원문 보기 →</a>{sim_btn}</div>
</div>"""


def _kind(reason: str) -> str:
    return (reason or "").split("(")[0].split(":")[0]


def drop_counts(d: dict) -> dict:
    """사유별 제외 건수(서로 다른 후보 기준). 목록은 사유별로 잘려 있어 집계는 drop_keys에서 가져온다."""
    c: dict = {}
    for k in (d.get("drop_keys") or {}).values():
        c[k] = c.get(k, 0) + 1
    for k in {_kind(x["reason"]) for x in d["dropped"]}:          # 옛 데이터(drop_keys 없음)는 목록으로 보충
        c[k] = max(c.get(k, 0), sum(1 for x in d["dropped"] if _kind(x["reason"]) == k))
    return c


def _dropped(d: dict) -> str:
    items = d["dropped"]
    if not items:
        return ""
    counts = drop_counts(d)
    total = sum(counts.values())
    by = " · ".join("%s %d" % (k, n) for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
    rows = "".join(
        '<div class="ex-item"><span class="ex-reason">%s</span><a href="%s" target="_blank" rel="noopener">%s</a>'
        ' <span class="ex-meta">%s · %s</span></div>'
        % (H.escape((d.get("reason") or "")[:34]), H.escape(d.get("url") or "#"), H.escape(d.get("title") or ""),
           H.escape(d.get("company") or ""), H.escape(d.get("press") or ""))
        for d in items)
    shown = ("사유별로 최대 40건씩 표시합니다. " if total > len(items) else "")
    return ('<details class="excluded"><summary>반영하지 않은 후보 %d건 — %s</summary>'
            '<div class="drop-list"><div class="f-note">%s제외 사유는 모든 후보에 기록됩니다.</div>%s</div></details>'
            % (total, H.escape(by), shown, rows))


FJS = """
(function(){
var menu=document.getElementById('menu'), qBox=document.getElementById('q'), clr=document.getElementById('clr'), hits=document.getElementById('hits');
if(!menu) return;
var co='all', q='';
var arts=Array.prototype.slice.call(document.querySelectorAll('.article'));
arts.forEach(function(a){ a.__txt=a.textContent.toLowerCase(); });
function clearMarks(){ document.querySelectorAll('mark').forEach(function(m){ var p=m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize(); }); }
function highlight(el, term){
  var w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false), nodes=[], n;
  while(n=w.nextNode()){ if(n.nodeValue.toLowerCase().indexOf(term)>-1) nodes.push(n); }
  nodes.forEach(function(node){
    var i=node.nodeValue.toLowerCase().indexOf(term); if(i<0) return;
    var after=node.splitText(i); after.splitText(term.length);
    var mk=document.createElement('mark'); mk.textContent=after.nodeValue; after.parentNode.replaceChild(mk, after);
  });
}
function apply(){
  clearMarks(); var shown=0, filtering=!!q || co!=='all';
  arts.forEach(function(a){
    var okCo=(co==='all' || a.dataset.cos.indexOf('|'+co+'|')>-1), okQ=(!q || a.__txt.indexOf(q)>-1), vis=okCo&&okQ;
    a.classList.toggle('hidden', !vis); if(vis){ shown++; if(q) highlight(a, q); }
  });
  document.querySelectorAll('.run-block').forEach(function(r){
    var vis=r.querySelectorAll('.article:not(.hidden)').length;
    r.classList.toggle('hidden', filtering && vis===0);
    r.open = filtering ? (vis>0) : (r.dataset.latest==='1');
    var cnt=r.querySelector('.cnt');
    if(cnt){ cnt.textContent = (filtering ? vis : (cnt.dataset.total||vis)) + '건'; cnt.classList.toggle('zero', filtering && vis===0); }
  });
  if(q){ hits.textContent='"'+q+'" 검색 결과 '+shown+'건'; hits.classList.add('show'); } else { hits.classList.remove('show'); }
  clr.classList.toggle('show', !!q);
}
menu.addEventListener('click', function(e){
  var b=e.target.closest('button'); if(!b||b.disabled) return;
  co=b.dataset.co; menu.querySelectorAll('button').forEach(function(x){ x.classList.toggle('active', x===b); }); apply();
});
var t=null; qBox.addEventListener('input', function(){ clearTimeout(t); t=setTimeout(function(){ q=qBox.value.trim().toLowerCase(); apply(); }, 180); });
clr.addEventListener('click', function(){ qBox.value=''; q=''; apply(); qBox.focus(); });
apply();
})();
"""


def render(days: list, companies: list, out_path: str = OUT_FILE, generated_at: str = "", limits: dict = None) -> str:
    limits = limits or {}
    sim: dict = {}
    total = sum(len(d["articles"]) for d in days)
    ndrop = sum(sum(drop_counts(d).values()) for d in days)
    counts: dict = {}
    for d in days:
        for a in d["articles"]:
            for c in [a["company"]] + a.get("also", []):
                counts[c] = counts.get(c, 0) + 1

    names = [c for c in companies if c in counts] + sorted(c for c in counts if c not in companies)
    menu = '<button data-co="all" class="active">전체 <span class="n">%d</span></button>' % total
    menu += "".join('<button data-co="%s">%s <span class="n">%d</span></button>'
                    % (H.escape(c), H.escape(c), counts[c]) for c in names)

    blocks = ""
    for i, d in enumerate(days):
        if not d["articles"] and not d["dropped"]:
            continue
        cards = "".join(_card(a, sim) for a in d["articles"]) or '<div class="f-note">이 날은 반영된 기사가 없습니다.</div>'
        blocks += f"""
<details class="run-block" data-latest="{1 if i == 0 else 0}"{" open" if i == 0 else ""}>
 <summary><div class="run-head"><span class="dot"></span><h2>{_day_label(d['date'])}</h2>
  <span class="cnt" data-total="{len(d['articles'])}">{len(d['articles'])}건</span>
  <span class="range">제외·미반영 {sum(drop_counts(d).values())}건</span><span class="caret">▾</span></div></summary>
 <div class="run-body">{cards}{_dropped(d)}</div>
</details>"""
    if not blocks:
        blocks = ('<div class="f-empty">아직 수집된 해외 기사가 없습니다.<br>'
                  'GitHub → Actions → <b>해외 영문 뉴스</b> → Run workflow 로 한 번 실행하세요.</div>')

    note = ("영문 매체의 JP모건·골드만삭스 등 해외 금융사 AI·디지털 기사를 구독 Claude가 한국어로 요약하고 제목도 번역합니다. "
            "하루 최대 %d건(회사당 %d건). 최근 3일 안의 기사만 받고, 주가·시황·투자유치 기사는 제외하며, 유료 매체는 본문이 실제로 읽힐 때만 반영합니다 "
            "(읽히지 않으면 아래 ‘반영하지 않은 후보’에 사유와 함께 남습니다). 국내 뉴스와 별도로 하루 3번 갱신됩니다."
            % (limits.get("max_per_day", 20), limits.get("max_per_company_per_day", 3)))
    sim_json = json.dumps(sim, ensure_ascii=False).replace("</", "<\\/")
    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>해외 금융사 AI 동향</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
<style>{hg.CSS}{EXTRA_CSS}</style></head><body>
<header><div class="eyebrow">Overseas Financial · AI News (English sources)</div>
<h1>해외 금융사 AI 동향</h1>
<div class="gen-meta">최종 갱신 {H.escape(generated_at)} · 누적 {total}건 · 구독 Claude 요약 · 별도 수집(국내 뉴스와 무관)</div></header>
<a class="back" href="{DOMESTIC_PAGE}">← 국내 뉴스</a>
<div class="ledger-line">{H.escape(note)}</div>
<div class="modal" id="shareModal">
  <div class="modal-box share-box">
    <h3>공유용 요약</h3>
    <textarea id="shareText" rows="9" spellcheck="false"></textarea>
    <div class="share-note" id="shareNote">내용을 고친 뒤 복사할 수 있습니다</div>
    <div class="modal-btns"><button id="shareClose">닫기</button><button class="primary" id="shareCopy">복사</button></div>
  </div>
</div>
<div class="modal" id="simModal">
  <div class="modal-box sim-box">
    <h3 id="simTitle">같은 사건 다른 매체</h3>
    <div class="sim-note">같은 사건으로 판단돼 카드로는 나타나지 않은 다른 매체 기사입니다. 제목을 누르면 원문이 열립니다.</div>
    <ul class="sim-list" id="simList"></ul>
    <div class="modal-btns"><button id="simClose">닫기</button></div>
  </div>
</div>
<div class="sticky">
  <nav class="company-menu" id="menu">{menu}</nav>
  <div class="search-wrap">
    <svg class="ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input type="search" id="q" placeholder="제목·요약·회사명 검색" autocomplete="off">
    <button class="clr" id="clr" aria-label="지우기">×</button>
  </div>
  <div class="search-hits" id="hits"></div>
</div>
{blocks}
<footer>해외(영문) 뉴스 트랙 — 반영 {total}건 · 미반영 기록 {ndrop}건 (최근 60일)</footer>
<script>window.__SIM__ = {sim_json};</script>
<script>{hg.COPY_JS}</script>
<script>{hg.SIM_JS}</script>
<script>{FJS}</script></body></html>"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path


def write_feed(days: list, path: str = FEED_FILE) -> str:
    """국내 페이지에 끼워 넣을 기사 목록(JSON). 제외 후보·본문 지문 같은 내부 값은 싣지 않는다.
    국내 HTML은 국내 실행만 만든다 — 해외 실행이 같은 파일을 쓰면 충돌하므로, 해외 쪽은 이 데이터 파일만 올리고
    국내 페이지가 열릴 때 읽는다(해외 실행이 끝나는 즉시 반영)."""
    arts = []
    for d in days:
        for a in d["articles"]:
            arts.append({k: a.get(k) for k in ("id", "company", "also", "title", "title_ko", "press", "url", "pub_date",
                                               "summary", "dups", "collected_at")})
    arts.sort(key=lambda a: (a.get("collected_at") or "", a.get("pub_date") or ""), reverse=True)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": datetime.now(store.KST).isoformat(timespec="seconds"), "articles": arts},
                  fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    return path


def build(cfg: dict, root: str = store.DATA_DIR, out_path: str = OUT_FILE, feed_path: str = FEED_FILE) -> str:
    fc = cfg.get("foreign", {})
    days = store.load_days(60, root)
    now = datetime.now(store.KST)
    write_feed(days, feed_path)
    return render(days, [c["name"] for c in fc.get("companies", [])], out_path,
                  generated_at=now.strftime("%Y-%m-%d %H:%M"), limits=fc)


if __name__ == "__main__":
    import yaml
    with open("config.yaml", encoding="utf-8") as fh:
        print(build(yaml.safe_load(fh)))
    sys.exit(0)
