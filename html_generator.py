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
    ("woori", "우리"), ("nh", "NH"), ("regional", "지방·국책"),
    ("nonholding", "비지주"),
    ("internet", "핀테크"), ("pubpolicy", "정책·규제"),
    ("overseas", "해외"), ("etc", "기타"),
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
/* 실행 버튼 */
.run-bar{display:flex;align-items:center;gap:9px;margin:10px 0 0}
.btn-run{font-family:inherit;font-size:13.5px;font-weight:800;color:#fff;background:var(--teal);
border:none;border-radius:8px;padding:9px 20px;cursor:pointer;display:flex;align-items:center;gap:6px}
.btn-run:hover{background:#005c65}
.btn-run:disabled{background:var(--muted);cursor:default}
.btn-run .spin{width:12px;height:12px;border:2px solid rgba(255,255,255,.4);border-top-color:#fff;
border-radius:50%;animation:sp .7s linear infinite;display:none}
.btn-run.busy .spin{display:block}
@keyframes sp{to{transform:rotate(360deg)}}
.run-status{font-size:12px;color:var(--muted);font-weight:600}
.run-status.ok{color:var(--teal)} .run-status.err{color:#b3403a}
.btn-key{font-family:inherit;font-size:11.5px;color:var(--muted);background:transparent;
border:1px solid var(--line);border-radius:6px;padding:5px 10px;cursor:pointer;margin-left:auto}

/* 토큰 입력 모달 */
.modal{position:fixed;inset:0;background:rgba(18,43,43,.5);display:none;align-items:center;
justify-content:center;z-index:50;padding:20px}
.modal.show{display:flex}
.modal-box{background:var(--card);border-radius:12px;padding:20px;max-width:400px;width:100%}
.modal-box h3{font-size:15px;font-weight:800;margin-bottom:8px}
.modal-box p{font-size:12.5px;color:var(--muted);margin-bottom:12px;line-height:1.55}
.modal-box p a{color:var(--teal);font-weight:600}
.modal-box input{width:100%;font-family:ui-monospace,monospace;font-size:12.5px;
border:1px solid var(--line);border-radius:7px;padding:9px 11px;outline:none;margin-bottom:12px}
.modal-box input:focus{border-color:var(--teal)}
.modal-btns{display:flex;gap:8px;justify-content:flex-end}
.modal-btns button{font-family:inherit;font-size:13px;font-weight:700;border-radius:7px;
padding:8px 16px;cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--muted)}
.modal-btns button.primary{background:var(--teal);border-color:var(--teal);color:#fff}

/* 1차 통과 검수 패널 */
.audit{margin:10px 0 0;background:var(--card);border:1px solid var(--line);border-radius:10px}
.audit>summary{cursor:pointer;padding:10px 14px;font-size:12.5px;font-weight:700;color:var(--muted);
list-style:none;display:flex;align-items:center;gap:8px}
.audit>summary::-webkit-details-marker{display:none}
.audit>summary::before{content:"▸";color:var(--teal);font-size:10px}
.audit[open]>summary::before{content:"▾"}
.audit-body{padding:0 14px 14px;max-height:520px;overflow-y:auto}
.audit-grp{margin-top:12px}
.audit-grp h4{font-size:11.5px;font-weight:800;color:var(--teal);margin-bottom:6px;
padding-bottom:4px;border-bottom:1px solid var(--line)}
.audit-item{font-size:11.5px;color:var(--ink);padding:4px 0;line-height:1.5}
.audit-item .meta{color:var(--muted);font-size:10.5px}
.audit-item a{color:var(--ink);text-decoration:none} .audit-item a:hover{color:var(--teal)}
.audit-dup{margin:2px 0 6px 14px;padding-left:10px;border-left:2px solid var(--line)}
.audit-dup div{font-size:11px;color:var(--muted);padding:2px 0}
.audit-why{color:var(--teal);font-weight:600;font-size:10.5px}

.a-meta.nosum{color:#b3403a}
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
.summary li::before{content:"–";position:absolute;left:0;color:var(--teal);font-weight:800}
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

RUN_JS = """
(function(){
var GH = window.__GH__ || {};
var KEY = 'fnews_gh_token';
var btn = document.getElementById('btnRun'), btnTxt = document.getElementById('btnRunTxt');
var stat = document.getElementById('runStatus'), keyBtn = document.getElementById('btnKey');
var modal = document.getElementById('tokenModal'), input = document.getElementById('tokenInput');
if(!btn) return;

function token(){ try { return localStorage.getItem(KEY); } catch(e){ return null; } }
function setToken(v){ try { localStorage.setItem(KEY, v); } catch(e){} }
function say(msg, cls){ stat.textContent = msg || ''; stat.className = 'run-status' + (cls ? ' '+cls : ''); }
function busy(on, label){
  btn.classList.toggle('busy', on); btn.disabled = on;
  btnTxt.textContent = label || (on ? '실행 중' : '실행');
}
function openModal(){ modal.classList.add('show'); input.value = token() || ''; input.focus(); }
function closeModal(){ modal.classList.remove('show'); }

document.getElementById('tokenCancel').onclick = closeModal;
document.getElementById('tokenSave').onclick = function(){
  var v = input.value.trim();
  if(!v){ return; }
  setToken(v); closeModal(); say('토큰이 저장되었습니다', 'ok');
};
keyBtn.onclick = openModal;
input.addEventListener('keydown', function(e){ if(e.key==='Enter') document.getElementById('tokenSave').click(); });

function headers(t){
  return { 'Authorization': 'Bearer ' + t, 'Accept': 'application/vnd.github+json',
           'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' };
}

async function poll(t, startedAt){
  var url = 'https://api.github.com/repos/'+GH.owner+'/'+GH.repo+'/actions/runs?per_page=5';
  for(var i=0; i<120; i++){
    await new Promise(function(r){ setTimeout(r, 6000); });
    try {
      var res = await fetch(url, { headers: headers(t) });
      if(!res.ok) continue;
      var data = await res.json();
      var run = (data.workflow_runs || []).find(function(r){
        return new Date(r.created_at).getTime() >= startedAt - 60000;
      });
      if(!run){ say('실행 대기 중…'); continue; }
      var mins = Math.floor((Date.now()-startedAt)/60000), secs = Math.floor(((Date.now()-startedAt)%60000)/1000);
      var el = mins + '분 ' + secs + '초';
      if(run.status === 'completed'){
        if(run.conclusion === 'success'){
          busy(false); say('완료 (' + el + ') · 새로고침합니다', 'ok');
          setTimeout(function(){ location.reload(true); }, 2000);
        } else {
          busy(false); say('실패: ' + (run.conclusion||'error') + ' — GitHub Actions에서 로그 확인', 'err');
        }
        return;
      }
      say((run.status === 'queued' ? '대기 중' : '수집 중') + '… ' + el);
    } catch(e){ /* 네트워크 일시 오류는 무시하고 계속 */ }
  }
  busy(false); say('시간 초과 — GitHub Actions에서 상태를 확인하세요', 'err');
}

btn.onclick = async function(){
  var t = token();
  if(!t){ openModal(); return; }
  busy(true, '요청 중'); say('워크플로 실행 요청…');
  var url = 'https://api.github.com/repos/'+GH.owner+'/'+GH.repo+'/actions/workflows/'+GH.workflow+'/dispatches';
  try {
    var res = await fetch(url, { method:'POST', headers: headers(t),
                                 body: JSON.stringify({ ref: GH.branch || 'main' }) });
    if(res.status === 204){
      var startedAt = Date.now();
      busy(true, '실행 중'); say('실행 시작됨…');
      poll(t, startedAt);
    } else if(res.status === 401 || res.status === 403){
      busy(false); say('토큰이 유효하지 않습니다. 토큰 변경을 눌러 다시 입력하세요', 'err'); openModal();
    } else if(res.status === 404){
      busy(false); say('워크플로를 찾을 수 없습니다 (' + GH.workflow + ')', 'err');
    } else {
      var msg = '';
      try { msg = (await res.json()).message || ''; } catch(e){}
      busy(false); say('요청 실패 (' + res.status + ') ' + msg, 'err');
    }
  } catch(e){
    busy(false); say('네트워크 오류: ' + e.message, 'err');
  }
};

if(!token()){ say('처음이면 실행을 눌러 토큰을 입력하세요'); }
})();
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
    var okCo  = (co==='all' || a.dataset.co===co ||
                 (co==='regional' && a.dataset.co==='policy'));
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
        lis = "".join("<li>%s</li>" % H.escape(l.lstrip("*-• ").strip())
                      for l in a["summary"].splitlines() if l.strip())
        summary = '<ul class="summary">%s</ul>' % lis
    else:
        # 사유를 함께 보여준다. 안 그러면 왜 없는지 알 수 없다.
        why = a["summary_fail_reason"] or ""
        _LBL = (
            ("레이트리밋(일일", "요약 미제공 — Groq 일일 한도 소진 (내일 오전 9시 이후 재시도)"),
            ("레이트리밋", "요약 미제공 — Groq 일일 한도 소진 (내일 오전 9시 이후 재시도)"),
            ("분당한도", "요약 미제공 — 순간 요청량 초과 (재실행하면 대부분 채워짐)"),
            ("본문 없음", "요약 미제공 — 본문 추출 실패 (매체 페이지 구조 문제)"),
            ("본문 부족", "요약 미제공 — 본문이 너무 짧아 요약 생략"),
            ("형식 검증", "요약 미제공 — 개조식 형식 미달 (요약하기 어려운 유형의 기사)"),
            ("환각", "요약 미제공 — 생성된 요약이 원문과 무관해 폐기"),
        )
        txt = "요약 미제공 — 원문 확인 필요"
        for k, v in _LBL:
            if why.startswith(k):
                txt = v
                break
        summary = '<div class="a-meta nosum">%s</div>' % H.escape(txt)
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


def _audit(screened):
    """1차 통과 기사의 최종 행방 — 중복 제거가 타당했는지 검수."""
    if not screened:
        return ""
    live = [a for a in screened if not a.get("excluded")]
    dup = [a for a in screened if (a.get("exclude_reason") or "").startswith("중복")]
    seen = [a for a in screened if (a.get("exclude_reason") or "").startswith("기열람")]
    irr = [a for a in screened
           if a.get("excluded") and not (a.get("exclude_reason") or "").startswith(("중복", "기열람"))]

    def item(a, extra=""):
        url = a.get("naver_url") or ""
        t = H.escape(a.get("title") or "")
        title = '<a href="%s" target="_blank">%s</a>' % (H.escape(url), t) if url else t
        return ('<div class="audit-item">%s <span class="meta">· %s</span>%s</div>'
                % (title, H.escape(a.get("press") or ""), extra))

    out = []
    if live:
        out.append('<div class="audit-grp"><h4>반영 %d건</h4>%s</div>'
                   % (len(live), "".join(item(a) for a in live)))
    if dup:
        reps = [a for a in screened if a.get("dup_members")]
        blocks = []
        for r in reps:
            members = "".join(
                '<div>└ %s <span class="meta">· %s</span> <span class="audit-why">%s</span></div>'
                % (H.escape(t), H.escape(p), H.escape(w))
                for t, p, w in r["dup_members"])
            blocks.append('%s<div class="audit-dup">%s</div>' % (item(r), members))
        out.append('<div class="audit-grp"><h4>중복 제거 %d건 → %d개 사건</h4>%s</div>'
                   % (len(dup), len(reps), "".join(blocks)))
    if seen:
        out.append('<div class="audit-grp"><h4>기열람 %d건 (직전 회차에 이미 반영)</h4>%s</div>'
                   % (len(seen), "".join(
                       item(a, ' <span class="audit-why">%s</span>'
                            % H.escape((a.get("exclude_reason") or "")[4:60]))
                       for a in seen[:60])))
    if irr:
        out.append('<div class="audit-grp"><h4>본문 확인 후 제외 %d건</h4>%s</div>'
                   % (len(irr), "".join(
                       item(a, ' <span class="meta">%s</span>'
                            % H.escape((a.get("exclude_reason") or "")[:40]))
                       for a in irr[:60])))

    return ('<details class="audit"><summary>1차 통과 %d건 검수 — 반영 %d · 중복 %d · '
            '기열람 %d · 본문무관 %d</summary><div class="audit-body">%s</div></details>'
            % (len(screened), len(live), len(dup), len(seen), len(irr), "".join(out)))


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


GH_CONF = {}


def render(rows, run_stats: dict, excluded_rows, out_path: str, history=None, gh=None,
           screened_rows=None):
    global GH_CONF
    GH_CONF = gh or {}
    runs = OrderedDict()
    counts = {k: 0 for k in MENU_LABELS}
    subs = {}          # menu_id -> {company: count}
    for a in rows:
        runs.setdefault(a["run_id"], {"meta": a, "arts": []})["arts"].append(a)
        counts["all"] += 1
        # 국책(policy)은 지방·국책(regional) 탭으로 합산
        grp = "regional" if a["fin_group"] == "policy" else a["fin_group"]
        counts[grp] = counts.get(grp, 0) + 1
        sec = a["sector"] or "기타"
        grp2 = "regional" if a["fin_group"] == "policy" else a["fin_group"]
        subs.setdefault(grp2, {})
        subs[grp2][sec] = subs[grp2].get(sec, 0) + 1

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
    audit = _audit(screened_rows or [])
    gh_json = json.dumps(GH_CONF, ensure_ascii=False)

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

    # 단계별 흐름 — 어디서 걸러졌는지 한눈에
    flow = ""
    if s.get("screened") is not None:
        flow = (' &nbsp;·&nbsp; 흐름: 수집 %d → 1차통과 %d → 중복제거후 %d → 반영 %d'
                % (s.get("raw", 0), s.get("screened", 0),
                   s.get("deduped", 0), s.get("final", 0)))
    # 제외 사유 상위
    reasons = s.get("exclude_reasons") or {}
    rtxt = ""
    if reasons:
        rtxt = (' &nbsp;·&nbsp; 제외 사유: '
                + ", ".join("%s %d" % (k, v) for k, v in reasons.items()))

    ledger = ('최근 회차 수지: 수집 <b>%d</b> = 반영 <b>%d</b> + 제외 %d &nbsp;·&nbsp; '
              'API %d콜 · 추출실패 %d · 요약실패 %d%s%s%s'
              % (s.get("raw", 0), s.get("final", 0), s.get("excluded", 0),
                 s.get("api_calls", 0), s.get("extract_fail", 0),
                 s.get("summary_fail", 0), warn_html, flow, rtxt))

    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>금융 디지털·AI 뉴스 아카이브</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
<style>{CSS}</style></head><body>
<header><div class="eyebrow">Financial Digital · AI News Archive</div>
<h1>금융회사 디지털·AI 뉴스 아카이브</h1>
<div class="gen-meta">최종 갱신 {s.get("generated_at","")} · 보관 60일 · 뉴스(네이버 API) + 보도자료(9개 그룹)</div></header>
<div class="run-bar">
  <button class="btn-run" id="btnRun"><span class="spin"></span><span id="btnRunTxt">실행</span></button>
  <span class="run-status" id="runStatus"></span>
  <button class="btn-key" id="btnKey">토큰 변경</button>
</div>
<div class="ledger-line">{ledger}</div>
{audit}

<div class="modal" id="tokenModal">
  <div class="modal-box">
    <h3>GitHub 토큰 입력</h3>
    <p>실행 권한 확인을 위해 개인 토큰이 필요합니다. 입력한 토큰은 이 브라우저에만 저장되며 서버로 전송되지 않습니다.<br><br>
    발급: GitHub → Settings → Developer settings → Personal access tokens (classic) → Generate new token → <b>repo</b>, <b>workflow</b> 체크</p>
    <input type="password" id="tokenInput" placeholder="ghp_..." autocomplete="off">
    <div class="modal-btns">
      <button id="tokenCancel">취소</button>
      <button class="primary" id="tokenSave">저장</button>
    </div>
  </div>
</div>
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
<script>window.__SUBS__ = {subs_json}; window.__GH__ = {gh_json};</script>
<script>{RUN_JS}</script>
<script>{JS}</script></body></html>"""

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path
