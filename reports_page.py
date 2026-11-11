# =============================================================
# reports_page.py — AI·디지털 보고서 페이지 (output/reports.html)
#
# 국내 페이지·해외 페이지와 파일이 따로다. 이 페이지는 보고서 트랙 워크플로만 만들고 커밋하므로
# 다른 실행과 파일이 겹치지 않는다(rebase 충돌 없음). 스타일은 국내 페이지의 것을 그대로 쓴다.
# =============================================================
import html as H
import os
import re
import sys
from datetime import datetime, timedelta

import html_generator as hg

OUT_FILE = os.path.join("output", "reports.html")
DOMESTIC_PAGE = "financial_news_archive.html"
WEEK = "월화수목금토일"
KINDS = ["보고서", "정책발표", "보도"]

EXTRA_CSS = """
.back{display:inline-block;font-size:12.5px;font-weight:700;color:var(--teal);text-decoration:none;
background:var(--teal-soft);border-radius:6px;padding:4px 12px;margin:4px 0 2px}
.back:hover{background:var(--teal);color:#fff}
.f-note{font-size:12px;color:var(--muted);margin:2px 0 10px;line-height:1.55}
.f-empty{font-size:13px;color:var(--muted);padding:26px 4px;line-height:1.7}
.fil{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding-bottom:8px}
.fil .lb{font-size:11.5px;font-weight:700;color:var(--muted);margin-right:2px}
.fil.orgs{flex-wrap:nowrap;overflow-x:auto;padding-bottom:10px;-webkit-overflow-scrolling:touch}
.fil.orgs button,.fil.orgs .lb{white-space:nowrap}
.filters{padding-top:2px}
.fil button{flex:0 0 auto;font-family:inherit;font-size:12.5px;font-weight:700;color:var(--muted);background:var(--card);
border:1px solid var(--line);border-radius:999px;padding:4px 11px;cursor:pointer}
.fil button.active{background:var(--teal);border-color:var(--teal);color:#fff}
.fil button .n{font-size:10.5px;opacity:.75;margin-left:3px}
.day-h{font-size:13px;font-weight:800;color:var(--ink);margin:20px 0 6px;padding-bottom:4px;border-bottom:1px solid var(--line)}
.day-h .c{font-weight:600;color:var(--muted);margin-left:6px;font-size:12px}
.r-desc{font-size:13px;line-height:1.6;color:var(--ink);margin:4px 0 2px;
display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.tag.reg{background:#eef1f0;color:var(--muted)} .tag.fin{background:var(--ai-soft);color:var(--ai)}
.tag.src-news{background:var(--warn-soft);color:var(--warn)} .tag.tr{background:#eef1f0;color:var(--muted)}
.r-orig{font-size:11.5px;line-height:1.45;color:var(--muted);margin:-1px 0 4px}
.drop-list{padding:0 14px 12px;max-height:420px;overflow-y:auto}
.ex-item a{color:inherit;text-decoration:none} .ex-item a:hover{text-decoration:underline}
details.excluded{margin-top:8px}
.src-state{font-size:12px;line-height:1.9;color:var(--muted)} .src-state .bad{color:#b3403a;font-weight:700}
.src-state .ok{color:var(--teal);font-weight:700}
"""


def _day_label(day: str) -> str:
    try:
        d = datetime.strptime(day, "%Y-%m-%d")
        return "%s (%s)" % (day, WEEK[d.weekday()])
    except ValueError:
        return day


def _card(it: dict) -> str:
    url = H.escape(it.get("url") or "#")
    kind = it.get("kind", "")
    tags = ('<span class="tag path">%s</span><span class="tag %s">%s</span>'
            % (H.escape(it["org"]), "src-news" if kind == "보도" else "digital", H.escape(kind)))
    if it.get("region") == "해외":
        tags += '<span class="tag reg">해외</span>'
    if it.get("finance"):
        tags += '<span class="tag fin">금융</span>'
    foreign_title = not re.search(r"[가-힣]", it["title"])               # 영문 항목: 번역이 있으면 한국어 제목을 앞에, 원제는 작게
    if foreign_title:
        tags += '<span class="tag tr">%s</span>' % ("번역" if it.get("title_ko") else "번역 전")
    show_title = it.get("title_ko") or it["title"]
    orig = '<div class="r-orig">원제: %s</div>' % H.escape(it["title"]) if it.get("title_ko") else ""
    meta = " · ".join(x for x in [it.get("sub") or "", ("%s%s" % (it["date"], " (수집일)" if it.get("date_est") else ""))] if x)
    shown_desc = it.get("desc_ko") or it.get("desc") or ""
    desc = '<div class="r-desc">%s</div>' % H.escape(shown_desc) if shown_desc else ""
    if it.get("also"):                                                    # 다른 기관이 같은 제목으로 낸 것(공동 보도자료 등)
        desc += '<div class="kw">함께 게시: %s</div>' % " · ".join(
            '<a href="%s" target="_blank" rel="noopener">%s</a>' % (H.escape(x["url"]), H.escape(x["org"])) for x in it["also"])
    kw = '<div class="kw">일치 단어: <b>%s</b></div>' % H.escape(", ".join(it.get("tags") or [])) if it.get("tags") else ""
    return f"""
<div class="article" data-org="{H.escape(it['org'])}" data-kind="{H.escape(kind)}" data-reg="{H.escape(it.get('region', ''))}" data-fin="{1 if it.get('finance') else 0}">
 <div class="tags">{tags}</div>
 <h3><a href="{url}" target="_blank" rel="noopener">{H.escape(show_title)}</a></h3>
 {orig}<div class="a-meta">{H.escape(meta)}</div>
 {desc}{kw}
 <div class="card-actions"><a class="src-link" href="{url}" target="_blank" rel="noopener">원문 보기 →</a></div>
</div>"""


def _dropped(items: list, cap: int = 400) -> str:
    if not items:
        return ""
    by: dict = {}
    for d in items:
        by[d["reason"]] = by.get(d["reason"], 0) + 1
    summ = " · ".join("%s %d" % (k, n) for k, n in sorted(by.items(), key=lambda kv: -kv[1]))
    rows = "".join(
        '<div class="ex-item"><span class="ex-reason">%s</span><a href="%s" target="_blank" rel="noopener">%s</a>'
        ' <span class="ex-meta">%s · %s</span></div>'
        % (H.escape(d["reason"]), H.escape(d["url"]), H.escape(d["title"]), H.escape(d["org"]), H.escape(d["date"]))
        for d in items[:cap])
    more = "최근 %d건만 표시합니다. " % cap if len(items) > cap else ""
    return ('<details class="excluded f-drop"><summary>반영하지 않은 후보 %d건 — %s</summary>'
            '<div class="drop-list"><div class="f-note">%s제목에 AI·디지털 핵심어가 없어 뺀 항목입니다. 잘못 빠졌다면 알려 주세요.</div>%s</div></details>'
            % (len(items), H.escape(summ), more, rows))


def _sources(sources: dict) -> str:
    if not sources:
        return ""
    parts = []
    for sid, s in sources.items():
        if s.get("ok"):
            parts.append('<span class="ok">✓ %s</span> %d건' % (H.escape(s["org"] + ("·" + sid if sid not in s["org"] else "")), s.get("n", 0)))
        else:
            parts.append('<span class="bad">✗ %s</span> %s' % (H.escape(s["org"]), H.escape(s.get("error", ""))))
    return ('<details class="excluded"><summary>수집원 상태 — 정상 %d · 실패 %d</summary><div class="drop-list">'
            '<div class="src-state">%s</div></div></details>'
            % (sum(1 for s in sources.values() if s.get("ok")), sum(1 for s in sources.values() if not s.get("ok")),
               "<br>".join(parts)))


RJS = """
(function(){
var st={kind:'all',reg:'all',org:'all',fin:false,q:''};
var arts=Array.prototype.slice.call(document.querySelectorAll('.article'));
arts.forEach(function(a){ a.__txt=a.textContent.toLowerCase(); });
var qBox=document.getElementById('q'), clr=document.getElementById('clr'), hits=document.getElementById('hits');
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
  clearMarks(); var shown=0;
  arts.forEach(function(a){
    var d=a.dataset;
    var ok=(st.kind==='all'||d.kind===st.kind)&&(st.reg==='all'||d.reg===st.reg)&&(st.org==='all'||d.org===st.org)&&(!st.fin||d.fin==='1')&&(!st.q||a.__txt.indexOf(st.q)>-1);
    a.classList.toggle('hidden', !ok); if(ok){ shown++; if(st.q) highlight(a, st.q); }
  });
  document.querySelectorAll('.day-blk').forEach(function(b){
    var v=b.querySelectorAll('.article:not(.hidden)').length; b.classList.toggle('hidden', v===0);
    var c=b.querySelector('.c'); if(c) c.textContent=v+'건';
  });
  var e=document.getElementById('none'); if(e) e.classList.toggle('hidden', shown>0);
  if(st.q){ hits.textContent='"'+st.q+'" 검색 결과 '+shown+'건'; hits.classList.add('show'); } else { hits.classList.remove('show'); }
  clr.classList.toggle('show', !!st.q);
  var f=document.getElementById('cnt'); if(f) f.textContent=shown;
}
document.querySelectorAll('.fil').forEach(function(g){
  g.addEventListener('click', function(e){
    var b=e.target.closest('button'); if(!b) return;
    var k=b.dataset.k;
    if(k==='fin'){ st.fin=!st.fin; b.classList.toggle('active', st.fin); }
    else { st[k]=b.dataset.v; g.querySelectorAll('button[data-k="'+k+'"]').forEach(function(x){ x.classList.toggle('active', x===b); }); }
    apply();
  });
});
var t=null; qBox.addEventListener('input', function(){ clearTimeout(t); t=setTimeout(function(){ st.q=qBox.value.trim().toLowerCase(); apply(); }, 180); });
clr.addEventListener('click', function(){ qBox.value=''; st.q=''; apply(); qBox.focus(); });
apply();
})();
"""


def _btn(k: str, v: str, label: str, n: int, active: bool = False) -> str:
    return '<button data-k="%s" data-v="%s"%s>%s <span class="n">%d</span></button>' % (
        k, H.escape(v), ' class="active"' if active else "", H.escape(label), n)


def render(store: dict, cfg: dict, out_path: str = OUT_FILE) -> str:
    days = cfg.get("reports", {}).get("lookback_days", 180)
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    items = [i for i in store.get("items", []) if i["date"] >= since]       # 조회 기간(기본 6개월) 이내만 보여 준다 — 저장소에는 그대로 남는다
    srcs = store.get("sources", {})
    total = len(items)
    kinds = {k: sum(1 for i in items if i.get("kind") == k) for k in KINDS}
    regs = {r: sum(1 for i in items if i.get("region") == r) for r in ("국내", "해외")}
    orgs: dict = {}
    for i in items:
        orgs[i["org"]] = orgs.get(i["org"], 0) + 1
    order = [s["org"] for s in cfg.get("reports", {}).get("sources", [])]
    org_names = sorted(orgs, key=lambda o: (order.index(o) if o in order else 99, o))

    fk = '<div class="fil"><span class="lb">구분</span>' + _btn("kind", "all", "전체", total, True) + \
         "".join(_btn("kind", k, k, kinds[k]) for k in KINDS if kinds[k]) + \
         '<span class="lb" style="margin-left:8px">지역</span>' + _btn("reg", "all", "전체", total, True) + \
         "".join(_btn("reg", r, r, n) for r, n in regs.items() if n) + \
         '<button data-k="fin" style="margin-left:8px">금융 관련만 <span class="n">%d</span></button></div>' % sum(1 for i in items if i.get("finance"))
    fo = '<div class="fil orgs"><span class="lb">기관</span>' + _btn("org", "all", "전체", total, True) + \
         "".join(_btn("org", o, o, orgs[o]) for o in org_names) + "</div>"

    blocks = ""
    day = None
    buf = []
    for it in items:                                                   # 이미 날짜 내림차순
        if it["date"] != day:
            if buf:
                blocks += '<div class="day-blk">%s</div>' % "".join(buf)
            day = it["date"]
            buf = ['<div class="day-h">%s<span class="c"></span></div>' % _day_label(day)]
        buf.append(_card(it))
    if buf:
        blocks += '<div class="day-blk">%s</div>' % "".join(buf)
    if not blocks:
        blocks = ('<div class="f-empty">아직 수집된 항목이 없습니다.<br>'
                  'GitHub → Actions → <b>AI·디지털 보고서</b> → Run workflow 로 한 번 실행하세요.</div>')
    else:
        blocks += '<div class="f-empty hidden" id="none">조건에 맞는 항목이 없습니다.</div>'

    ok = sum(1 for s in srcs.values() if s.get("ok"))
    scope = "최근 %d일 이내" % days + (", 정책 발표는 싣지 않음" if "정책발표" in (cfg.get("reports", {}).get("exclude_kinds") or []) else "")
    note = ("금융위원회·금융감독원·한국은행·금융보안원·자본시장연구원·KISA·삼정KPMG·EY한영·BIS 등이 공개한 AI·디지털 관련 보고서를 모았습니다(%s). " % scope +
            "제목에 AI·디지털 핵심어가 있는 것만 싣고, 요약은 하지 않고 기관이 공개한 설명을 그대로 보여 줍니다. "
            "해외(영문) 항목은 제목·설명을 AI(Claude)로 한국어 번역해 보여 주고 원제를 함께 적습니다(번역 전·실패 시 영문 그대로). "
            "삼일PwC처럼 자동 접속을 막는 곳은 ‘보도’ 구분으로 발간 소식 기사만 잡습니다. 걸러진 항목은 맨 아래에 사유와 함께 남습니다.")
    now = store.get("updated") or datetime.now().strftime("%Y-%m-%d %H:%M")
    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI·디지털 보고서</title>
{hg.FAVICON_LINKS}
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
<style>{hg.CSS}{EXTRA_CSS}</style></head><body>
<header class="hd"><div class="hd-text"><div class="eyebrow">AI · Digital Reports &amp; Policy</div>
<h1>AI·디지털 보고서</h1>
<div class="gen-meta">최종 갱신 {H.escape(now)} · 누적 {total}건 · 수집원 {ok}/{len(srcs)} 정상 · 별도 수집(국내 뉴스와 무관)</div></div>{hg.MASCOT_HTML}</header>
<a class="back" href="{DOMESTIC_PAGE}">← 국내 뉴스</a>
<div class="ledger-line">{H.escape(note)}</div>
<div class="filters">{fk}{fo}</div>
<div class="sticky">
  <div class="search-wrap">
    <svg class="ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input type="search" id="q" placeholder="제목·설명·기관 검색" autocomplete="off">
    <button class="clr" id="clr" aria-label="지우기">×</button>
  </div>
  <div class="search-hits" id="hits"></div>
</div>
{blocks}
{_dropped(store.get("dropped", []))}
{_sources(srcs)}
<footer>보고서 트랙 — 표시 <span id="cnt">{total}</span>건 · 제외 기록 {len(store.get("dropped", []))}건 (최근 60일)</footer>
<script>{RJS}</script></body></html>"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path


if __name__ == "__main__":
    import yaml
    import reports
    with open("config.yaml", encoding="utf-8") as fh:
        print(render(reports.load_store(), yaml.safe_load(fh)))
    sys.exit(0)
