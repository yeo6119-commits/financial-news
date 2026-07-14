# =============================================================
# html_generator.py — 아카이브 HTML 렌더링 (v2.5)
# 변경점:
#   1) B안 메뉴: 탭 11개 (증권/카드보험 → '비지주 금융사'로 통합)
#   2) 탭 내부에서 회사별 소제목으로 구분
#   3) AI / 디지털 서브 필터 (회사 탭과 독립 동작)
# =============================================================
import html as H
import os
from collections import OrderedDict
from datetime import datetime

MENU_LABELS = OrderedDict([
    ("all", "전체"), ("hana", "하나"), ("shinhan", "신한"), ("kb", "KB"),
    ("woori", "우리"), ("nh", "NH"), ("regional", "지방금융"),
    ("policy", "국책"), ("nonholding", "비지주"),
    ("internet", "핀테크"), ("overseas", "해외"), ("etc", "기타"),
])
SECTOR_ORDER = ["그룹", "은행", "증권", "카드", "캐피탈", "보험", "저축은행", "해외", "기타"]

CSS = """
:root{--ink:#122b2b;--paper:#f7f9f8;--card:#fff;--teal:#00707a;--teal-soft:#e3f0f0;
--ai:#3f4d9e;--ai-soft:#e9ebf7;--line:#d8e2e0;--muted:#6a7c7a;--warn:#a05a1f;--warn-soft:#f6ecdf}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Pretendard,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
background:var(--paper);color:var(--ink);line-height:1.6;padding:16px 14px 60px;max-width:880px;margin:0 auto}
header{padding-bottom:8px}
.eyebrow{font-size:11px;letter-spacing:.14em;color:var(--teal);font-weight:700;text-transform:uppercase}
h1{font-size:21px;font-weight:800;margin-top:2px}
.gen-meta{font-size:12px;color:var(--muted);margin-top:4px}
.ledger-line{font-size:12px;color:var(--muted);background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:7px 12px;margin:10px 0 12px;font-variant-numeric:tabular-nums}
.ledger-line b{color:var(--teal)} .ledger-line .warn{color:var(--warn);font-weight:600}
.sticky{position:sticky;top:0;z-index:5;background:var(--paper);padding-top:6px;border-bottom:2px solid var(--teal)}
nav.company-menu{display:flex;flex-wrap:wrap;gap:6px;padding-bottom:8px}
nav.company-menu button{flex:0 0 auto;font-family:inherit;font-size:13px;font-weight:700;color:var(--muted);
background:var(--card);border:1px solid var(--line);border-radius:20px;padding:6px 13px;cursor:pointer}
nav.company-menu button.active{background:var(--teal);border-color:var(--teal);color:#fff}
nav.company-menu button .n{font-size:11px;opacity:.75;margin-left:3px}
nav.sub-menu{display:flex;gap:5px;overflow-x:auto;padding:0 0 8px}
nav.sub-menu button{flex:0 0 auto;font-family:inherit;font-size:12px;font-weight:600;color:var(--muted);
background:transparent;border:1px solid var(--line);border-radius:6px;padding:4px 11px;cursor:pointer;white-space:nowrap}
nav.sub-menu button.active{background:var(--ink);border-color:var(--ink);color:#fff}
nav.sub-menu button .n{font-size:10.5px;opacity:.7;margin-left:3px}
nav.sub-menu.hidden{display:none}
.search-wrap{position:relative;padding:0 0 9px}
.search-wrap input{width:100%;font-family:inherit;font-size:13.5px;color:var(--ink);
background:var(--card);border:1px solid var(--line);border-radius:8px;
padding:8px 34px 8px 32px;outline:none}
.search-wrap input:focus{border-color:var(--teal)}
.search-wrap input::placeholder{color:var(--muted)}
.search-wrap .ico{position:absolute;left:10px;top:8px;width:15px;height:15px;
stroke:var(--muted);fill:none;stroke-width:2}
.search-wrap .clr{position:absolute;right:8px;top:6px;border:none;background:transparent;
color:var(--muted);font-size:16px;cursor:pointer;padding:2px 6px;display:none}
.search-wrap .clr.show{display:block}
.search-hits{font-size:11.5px;color:var(--teal);font-weight:600;padding:0 0 8px;display:none}
.search-hits.show{display:block}
mark{background:#fff3b0;color:inherit;border-radius:2px;padding:0 1px}

/* 회차 이력 패널 */
details.runlog{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:0 0 14px}
details.runlog summary{cursor:pointer;list-style:none;padding:9px 13px;font-size:12.5px;
font-weight:700;color:var(--teal)}
details.runlog summary::-webkit-details-marker{display:none}
details.runlog summary::after{content:"▾";float:right;color:var(--muted);font-weight:400}
details.runlog[open] summary::after{content:"▴"}
.rl-wrap{padding:0 13px 11px;max-height:300px;overflow-y:auto}
.rl-row{display:flex;align-items:baseline;gap:8px;font-size:12.5px;padding:6px 0;
border-bottom:1px dashed var(--line);font-variant-numeric:tabular-nums}
.rl-row:last-child{border-bottom:none}
.rl-when{font-weight:700;color:var(--ink);min-width:132px}
.rl-ok{color:var(--teal);font-weight:700}
.rl-sub{color:var(--muted);font-size:11.5px}
.rl-fail{color:var(--warn);font-weight:600}
.run-block{margin-top:18px}
.run-block>summary{list-style:none;cursor:pointer}
.run-block>summary::-webkit-details-marker{display:none}
.run-head{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}
.run-head .dot{width:9px;height:9px;border-radius:50%;background:var(--teal);flex:0 0 auto}
.run-head h2{font-size:14.5px;font-weight:800} .run-head .range{font-size:11.5px;color:var(--muted)}
.run-head .cnt{font-size:11px;font-weight:700;color:var(--teal);background:var(--teal-soft);
border-radius:20px;padding:1px 9px}
.run-head .cnt.zero{color:var(--muted);background:#eef1f0}
.run-head .caret{margin-left:auto;color:var(--muted);font-size:12px;transition:transform .15s}
.run-block[open] .run-head .caret{transform:rotate(180deg)}
.run-block:not([open]) .run-head .dot{background:var(--muted)}
.run-block:not([open]) .run-head h2{font-weight:700;color:var(--muted)}
.run-body{border-left:2px solid var(--line);margin-left:4px;padding-left:14px}
.co-group{margin-bottom:2px}
.article{border:1px solid var(--line);border-left:4px solid var(--teal);border-radius:8px;
padding:11px 14px;margin-bottom:10px;background:var(--card)}
.article.is-ai{border-left-color:var(--ai)}
.tags{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:5px}
.tag{font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:4px}
.tag.path{background:#eef1f0;color:var(--muted)} .tag.digital{background:var(--teal-soft);color:var(--teal)}
.tag.ai{background:var(--ai-soft);color:var(--ai)} .tag.pr{background:var(--warn-soft);color:var(--warn)}
.tag.fail{background:#fbe9e7;color:#b3403a}
.article h3{font-size:15px;font-weight:700}
.article h3 a{color:inherit;text-decoration:none}
.article h3 a:hover{border-bottom:1px solid var(--teal)}
.a-meta{font-size:11.5px;color:var(--muted);margin:2px 0 7px}
.summary{list-style:none}
.summary li{font-size:13.5px;padding-left:14px;position:relative;margin-bottom:3px}
.summary li::before{content:"*";position:absolute;left:0;color:var(--teal);font-weight:800}
.article.is-ai .summary li::before{color:var(--ai)}
.kw{font-size:11px;color:var(--muted);margin-top:7px} .kw b{color:var(--teal);font-weight:600}
.src-link{display:inline-block;margin-top:8px;font-size:12.5px;font-weight:700;color:var(--teal);
text-decoration:none;background:var(--teal-soft);border-radius:6px;padding:4px 12px}
.src-link:hover{background:var(--teal);color:#fff}
.article.is-ai .src-link{color:var(--ai);background:var(--ai-soft)}
.article.is-ai .src-link:hover{background:var(--ai);color:#fff}
details.excluded{background:var(--warn-soft);border:1px solid #e8d5bc;border-radius:8px;margin-top:24px}
details.excluded summary{cursor:pointer;list-style:none;padding:10px 14px;font-size:12.5px;color:var(--warn);font-weight:700}
.ex-wrap{padding:0 14px 12px;max-height:420px;overflow-y:auto}
.ex-item{font-size:12.5px;padding:6px 0;border-bottom:1px dashed #e8d5bc;display:flex;flex-wrap:wrap;gap:4px 8px}
.ex-item:last-child{border-bottom:none}
.ex-reason{font-size:10.5px;font-weight:700;color:var(--warn);background:#fff;border-radius:4px;padding:1px 7px;white-space:nowrap}
.ex-meta{color:var(--muted);font-size:11px}
footer{margin-top:24px;font-size:11px;color:var(--muted);text-align:center}
.hidden{display:none} .empty-run{font-size:12.5px;color:var(--muted);padding:6px 0 2px}
"""

JS = """
(function(){
var coMenu=document.getElementById('menu'), subMenu=document.getElementById('submenu');
var qBox=document.getElementById('q'), clr=document.getElementById('clr'), hits=document.getElementById('hits');
if(!coMenu)return;
var co='all', sub='all', q='';
var SUBS = window.__SUBS__ || {};
var arts = Array.prototype.slice.call(document.querySelectorAll('.article'));

// 검색 대상 텍스트 캐시
arts.forEach(function(a){ a.__txt = a.textContent.toLowerCase(); });

function clearMarks(){
  document.querySelectorAll('mark').forEach(function(m){
    var p=m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize();
  });
}
function highlight(el, term){
  if(!term) return;
  var walker=document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false), nodes=[], n;
  while(n=walker.nextNode()){ if(n.nodeValue.toLowerCase().indexOf(term)>-1) nodes.push(n); }
  nodes.forEach(function(node){
    var idx=node.nodeValue.toLowerCase().indexOf(term);
    if(idx<0) return;
    var after=node.splitText(idx), rest=after.splitText(term.length);
    var mk=document.createElement('mark'); mk.textContent=after.nodeValue;
    after.parentNode.replaceChild(mk, after);
  });
}
function renderSub(){
  if(co==='all' || !SUBS[co] || SUBS[co].length<2){ subMenu.classList.add('hidden'); sub='all'; return; }
  subMenu.classList.remove('hidden');
  var total = SUBS[co].reduce(function(s,x){return s+x[1];},0);
  var html = '<button data-sub="all" class="active">전체 <span class="n">'+total+'</span></button>';
  SUBS[co].forEach(function(x){
    html += '<button data-sub="'+x[0]+'">'+x[0]+' <span class="n">'+x[1]+'</span></button>';
  });
  subMenu.innerHTML = html; sub='all';
}
function apply(){
  clearMarks();
  var shown=0;
  var filtering = !!q || co!=='all' || sub!=='all';
  arts.forEach(function(a){
    var okCo  = (co==='all'  || a.dataset.co===co);
    var okSub = (sub==='all' || a.dataset.sector===sub);
    var okQ   = (!q || a.__txt.indexOf(q)>-1);
    var vis = okCo && okSub && okQ;
    a.classList.toggle('hidden', !vis);
    if(vis){ shown++; if(q) highlight(a, q); }
  });
  document.querySelectorAll('.co-group').forEach(function(g){
    g.classList.toggle('hidden', g.querySelectorAll('.article:not(.hidden)').length===0);
  });
  document.querySelectorAll('.run-block').forEach(function(r){
    var vis=r.querySelectorAll('.article:not(.hidden)').length;
    var em=r.querySelector('.empty-run');
    if(vis===0){
      if(!em){em=document.createElement('div');em.className='empty-run';
        em.textContent='이 회차에는 해당 조건의 기사가 없습니다.';r.querySelector('.run-body').appendChild(em);}
      em.classList.remove('hidden');
    } else if(em){ em.classList.add('hidden'); }

    // 자동 펼침 없음 — 사용자가 클릭할 때만 열림.
    // 대신 헤더 배지에 현재 조건의 매칭 건수를 표시.
    var cnt = r.querySelector('.cnt');
    if(cnt){
      if(filtering){
        cnt.textContent = vis + '건';
        cnt.classList.toggle('zero', vis===0);
      } else {
        cnt.textContent = (cnt.dataset.total || vis) + '건';
        cnt.classList.remove('zero');
      }
    }
  });
  if(q){ hits.textContent='"'+q+'" 검색 결과 '+shown+'건'; hits.classList.add('show'); }
  else { hits.classList.remove('show'); }
  clr.classList.toggle('show', !!q);
}
coMenu.addEventListener('click',function(e){
  var b=e.target.closest('button'); if(!b||b.disabled)return;
  co=b.dataset.co;
  coMenu.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b);});
  renderSub(); apply();
});
subMenu.addEventListener('click',function(e){
  var b=e.target.closest('button'); if(!b)return;
  sub=b.dataset.sub;
  subMenu.querySelectorAll('button').forEach(function(x){x.classList.toggle('active',x===b);});
  apply();
});
var t=null;
qBox.addEventListener('input',function(){
  clearTimeout(t);
  t=setTimeout(function(){ q=qBox.value.trim().toLowerCase(); apply(); }, 180);
});
clr.addEventListener('click',function(){ qBox.value=''; q=''; apply(); qBox.focus(); });
renderSub(); apply();
})();
"""


def _card(a) -> str:
    is_ai = a["dig_ai"] == "AI"
    is_pr = (a["search_keyword"] or "").startswith("[PR]")
    url = a["naver_url"] or a["original_url"] or "#"
    status = ""
    if not a["extract_ok"]:
        status = '<span class="tag fail">본문 추출 실패</span>'
    elif not a["summary_ok"]:
        status = '<span class="tag fail">요약 실패</span>'
    if a["summary"]:
        lis = "".join("<li>%s</li>" % H.escape(l.lstrip("* ").strip())
                      for l in a["summary"].splitlines() if l.strip())
        summary = '<ul class="summary">%s</ul>' % lis
    else:
        summary = '<div class="a-meta">요약 미제공 — 원문 확인 필요</div>'
    pr_tag = '<span class="tag pr">보도자료</span>' if is_pr else ""
    pub = (a["pub_date"] or "")[:16].replace("T", " ")
    cls = " is-ai" if is_ai else ""
    company = a["company"] or a["subgroup"] or ""
    return f"""
<div class="article{cls}" data-co="{a['fin_group']}" data-sector="{H.escape(a['sector'] or '기타')}" data-type="{a['dig_ai']}">
 <div class="tags"><span class="tag path">{H.escape(company)} · {H.escape(a['sector'] or '')}</span>
 <span class="tag {'ai' if is_ai else 'digital'}">{a['dig_ai']}</span>{pr_tag}{status}</div>
 <h3><a href="{H.escape(url)}" target="_blank" rel="noopener">{H.escape(a['title'])}</a></h3>
 <div class="a-meta">{H.escape(a['press'] or '')} · {pub}</div>
 {summary}
 <div class="kw">매칭 키워드: <b>{H.escape(a['matched_keywords'] or '-')}</b></div>
 <a class="src-link" href="{H.escape(url)}" target="_blank" rel="noopener">원문 보기 →</a>
</div>"""


def _sector_key(s):
    return SECTOR_ORDER.index(s) if s in SECTOR_ORDER else len(SECTOR_ORDER)


WEEK = "월화수목금토일"


def _runlog(history) -> str:
    """회차별 요청 이력 패널 — 요청 일시 / 반영 / 요약 성공"""
    if not history:
        return ""
    items = ""
    for r in history:
        req = r["requested_at"] or ""
        try:
            dt = datetime.fromisoformat(req)
            when = f"{dt:%Y-%m-%d} ({WEEK[dt.weekday()]}) {dt:%H:%M}"
        except (ValueError, TypeError):
            when = req[:16].replace("T", " ")
        ok, fail = r["summary_ok_cnt"] or 0, r["summary_fail_cnt"] or 0
        dl = r["delivered_cnt"] or 0
        fail_html = f' <span class="rl-fail">요약실패 {fail}</span>' if fail else ""
        items += (f'<div class="rl-row"><span class="rl-when">{H.escape(when)} 요청</span>'
                  f'<span class="rl-ok">{dl}건 반영</span>'
                  f'<span class="rl-sub">요약 성공 {ok}</span>{fail_html}'
                  f'<span class="rl-sub">· 수집 {r["raw_collected"] or 0} · API {r["api_calls"] or 0}콜</span>'
                  f'</div>')
    total = sum((r["delivered_cnt"] or 0) for r in history)
    return (f'<details class="runlog"><summary>요청 이력 {len(history)}회 · 누적 {total}건 반영</summary>'
            f'<div class="rl-wrap">{items}</div></details>')


def render(rows, run_stats: dict, excluded_rows, out_path: str, history=None):
    runs = OrderedDict()
    counts = {k: 0 for k in MENU_LABELS}
    subs = {}          # menu_id -> {company: count}
    for a in rows:
        runs.setdefault(a["run_id"], {"meta": a, "arts": []})["arts"].append(a)
        counts["all"] += 1
        counts[a["fin_group"]] = counts.get(a["fin_group"], 0) + 1
        sec = a["sector"] or "기타"
        subs.setdefault(a["fin_group"], {})
        subs[a["fin_group"]][sec] = subs[a["fin_group"]].get(sec, 0) + 1

    # 업권 순으로 고정 정렬 (그룹 → 은행 → 증권 → 카드 → 캐피탈 → 보험 → 저축은행 → 해외 → 기타)
    sub_js = {}
    for mid, secs in subs.items():
        ordered = sorted(secs.items(), key=lambda x: _sector_key(x[0]))
        sub_js[mid] = [[s, n] for s, n in ordered]

    # 모든 탭 상시 표시 (0건이어도 고정 위치 유지 — 위치 기억 용이)
    # 단, 'etc'(미분류)는 실제 기사가 있을 때만 노출
    menu = "".join(
        '<button data-co="%s"%s%s>%s <span class="n">%d</span></button>'
        % (k, ' class="active"' if k == "all" else "",
           ' disabled style="opacity:.45;cursor:default"' if counts.get(k, 0) == 0 and k != "all" else "",
           v, counts.get(k, 0))
        for k, v in MENU_LABELS.items() if k != "etc" or counts.get("etc", 0) > 0)

    import json
    subs_json = json.dumps(sub_js, ensure_ascii=False)
    runlog = _runlog(history or [])

    run_html = ""
    for i, (rid, r) in enumerate(runs.items()):
        m = r["meta"]
        req = (m["run_requested"] or "")[:16].replace("T", " ")
        rng = "검색 %s ~ %s" % ((m["run_start"] or "")[5:16].replace("T", " "),
                               (m["run_end"] or "")[5:16].replace("T", " "))
        # 발행일 최신순 정렬 (pub_date 내림차순)
        blocks = "".join(_card(a) for a in sorted(
            r["arts"], key=lambda x: (x["pub_date"] or ""), reverse=True))
        # 최신 회차만 펼침, 과거 요청분은 접어둠
        is_latest = (i == 0)
        opened = " open" if is_latest else ""
        label = f"{req} 요청분" + ("" if is_latest else " (과거)")
        run_html += f"""
<details class="run-block"{opened}>
 <summary>
  <div class="run-head"><span class="dot"></span><h2>{label}</h2>
   <span class="cnt" data-total="{len(r['arts'])}">{len(r['arts'])}건</span>
   <span class="range">{rng}</span><span class="caret">▾</span></div>
 </summary>
 <div class="run-body">{blocks}</div>
</details>"""

    ex_html = ""
    if excluded_rows:
        items = "".join(
            '<div class="ex-item"><span class="ex-reason">%s</span>%s <span class="ex-meta">%s · %s</span></div>'
            % (H.escape((e["exclude_reason"] or "")[:26]), H.escape(e["title"]),
               H.escape(e["press"] or ""), (e["pub_date"] or "")[:10])
            for e in excluded_rows[:400])
        ex_html = ('<details class="excluded"><summary>이번 회차 제외 목록 %d건 — 검수용</summary>'
                   '<div class="ex-wrap">%s</div></details>' % (len(excluded_rows), items))

    s = run_stats
    warn = []
    if s.get("cutoff_keywords"):
        warn.append("절단: %s" % H.escape(s["cutoff_keywords"][:60]))
    if s.get("truncated_from"):
        warn.append("72h 초과 잘림: %s 이전" % s["truncated_from"][:16])
    pr_fail = [k for k, v in (s.get("press_health") or {}).items() if not v.startswith("ok")]
    if pr_fail:
        warn.append("PR 실패: %s" % ", ".join(pr_fail))
    warn_html = ' · <span class="warn">%s</span>' % " / ".join(warn) if warn else ""

    ledger = ('최근 회차 수지: 수집 <b>%d</b> = 반영 <b>%d</b> + 제외 %d &nbsp;·&nbsp; '
              'API %d콜 · 추출실패 %d · 요약실패 %d%s'
              % (s.get("raw", 0), s.get("final", 0), s.get("excluded", 0),
                 s.get("api_calls", 0), s.get("extract_fail", 0),
                 s.get("summary_fail", 0), warn_html))

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>금융 디지털·AI 뉴스 아카이브</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
<style>{CSS}</style></head><body>
<header><div class="eyebrow">Financial Digital · AI News Archive</div>
<h1>금융회사 디지털·AI 뉴스 아카이브</h1>
<div class="gen-meta">최종 갱신 {s.get("generated_at","")} · 보관 60일 · 뉴스(네이버 API) + 보도자료(9개 그룹)</div></header>
<div class="ledger-line">{ledger}</div>
{runlog}
<div class="sticky">
  <nav class="company-menu" id="menu">{menu}</nav>
  <nav class="sub-menu hidden" id="submenu"></nav>
  <div class="search-wrap">
    <svg class="ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input type="search" id="q" placeholder="제목·요약·회사명 검색" autocomplete="off">
    <button class="clr" id="clr" aria-label="지우기">×</button>
  </div>
  <div class="search-hits" id="hits"></div>
</div>
{run_html}
{ex_html}
<footer>금융 디지털·AI 뉴스 수집 시스템 v2.5 — 수집은 넓게, 판단은 본문 확보 후 로컬에서</footer>
<script>window.__SUBS__ = {subs_json};</script>
<script>{JS}</script></body></html>"""

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path
