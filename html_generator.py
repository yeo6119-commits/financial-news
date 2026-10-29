# =============================================================
# html_generator.py — 아카이브 HTML 렌더링 (v2.5)
# 변경점:
#   1) B안 메뉴: 탭 11개 (증권/카드보험 → '비지주 금융사'로 통합)
#   2) 탭 내부에서 회사별 소제목으로 구분
#   3) AI / 디지털 서브 필터 (회사 탭과 독립 동작)
# =============================================================
import html as H
import os
import re
from collections import OrderedDict
from datetime import datetime

import outlets

MENU_LABELS = OrderedDict([
    ("all", "전체"),
    ("hana", "하나"), ("shinhan", "신한"), ("kb", "KB"),
    ("woori", "우리"), ("nh", "NH"), ("internet", "핀테크"),
    ("overseas", "해외"), ("etc", "기타"),
])
# '기타' 탭이 흡수하는 그룹 (지방·국책, 비지주 증권/카드보험, 미분류)
ETC_GROUPS = {"regional", "policy", "nonholding", "securities", "cardins", "etc"}
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
.btn-run-f{background:var(--ai)} .btn-run-f:hover{background:#333f85}
.run-stats{display:flex;flex-direction:column;gap:2px;margin:6px 0 0}
.run-stats .run-status:empty{display:none}
.run-link{color:var(--teal);font-weight:800;text-decoration:none} .run-link:hover{text-decoration:underline}
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
.rep-ok{font-size:10px;font-weight:800;color:#0a7d55;background:#e4f5ec;
padding:1px 6px;border-radius:9px;white-space:nowrap}
.rep-out{font-size:10px;font-weight:700;color:var(--warn);background:var(--warn-soft);
padding:1px 6px;border-radius:9px}
.seen-group{margin:8px 0 4px;border-top:1px dashed var(--line);padding-top:6px}
.seen-group>summary{cursor:pointer;font-size:11.5px;font-weight:700;color:var(--ink)}
.seen-group>summary::-webkit-details-marker{display:none}
.seen-group>summary::before{content:"▸ ";color:var(--muted);font-size:9px}
.seen-group[open]>summary::before{content:"▾ "}
.seen-cluster{margin:6px 0 4px 12px;padding-left:10px;border-left:2px solid var(--teal-soft)}
.seen-ref{font-size:10.5px;color:var(--teal);font-weight:700;margin-bottom:2px}
.seen-ref .co{color:var(--ink);font-weight:800}
.seen-ref .date{color:var(--muted);font-weight:600}
.seen-cluster .audit-item{padding:2px 0}
.seen-more{margin-top:2px}
.seen-more>summary{cursor:pointer;font-size:10.5px;color:var(--muted);font-weight:600}
.seen-more>summary::-webkit-details-marker{display:none}
.seen-more>summary::before{content:"▸ "}
.seen-more[open]>summary::before{content:"▾ "}
.rep-dup{font-size:10px;font-weight:700;color:var(--muted);background:var(--paper);
padding:1px 6px;border-radius:9px;border:1px solid var(--line)}

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
/* 해외(영문) 트랙은 별도 페이지 — 필터가 아니라 링크 */
nav.company-menu a.f-link{flex:0 0 auto;font-size:13px;font-weight:700;color:var(--teal);text-decoration:none;
background:var(--card);border:1px dashed var(--teal);border-radius:20px;padding:6px 13px}
nav.company-menu a.f-link:hover{background:var(--teal);color:#fff}
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
.article{position:relative}
/* 공유용 요약 복사 버튼 — 라벨은 ::before로 그려 검색(textContent)에 잡히지 않게 한다 */
.copy-sum{position:absolute;top:9px;right:12px;font-family:inherit;font-size:12px;font-weight:800;
color:var(--teal);background:var(--teal-soft);border:1px solid transparent;border-radius:6px;
padding:4px 12px;cursor:pointer;line-height:1.3}
.copy-sum::before{content:"요약"}
.copy-sum:hover{background:var(--teal);color:#fff}
.article.is-ai .copy-sum{color:var(--ai);background:var(--ai-soft)}
.article.is-ai .copy-sum:hover{background:var(--ai);color:#fff}
.article.has-sum .tags{padding-right:84px}
/* 원문 보기 옆 '비슷한 기사' 단추 — 라벨은 ::before로 그려 검색(textContent)에 잡히지 않게 한다 */
.card-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}
.card-actions .src-link{margin-top:0}
.sim-btn{font-family:inherit;font-size:12.5px;font-weight:700;color:var(--muted);background:var(--card);
border:1px solid var(--line);border-radius:6px;padding:4px 12px;cursor:pointer;line-height:1.3}
.sim-btn::before{content:"비슷한 기사 " attr(data-n)}
.sim-btn:hover{color:var(--teal);border-color:var(--teal)}
.article.is-ai .sim-btn:hover{color:var(--ai);border-color:var(--ai)}
/* 비슷한 기사 팝업 */
.sim-box{max-width:600px}
.sim-note{font-size:11.5px;color:var(--muted);margin-bottom:10px;line-height:1.5}
.sim-list{list-style:none;max-height:56vh;overflow-y:auto;margin-bottom:12px;border-top:1px solid var(--line)}
.sim-list li{padding:9px 2px;border-bottom:1px solid var(--line);display:flex;flex-direction:column;gap:2px}
.sim-press{font-size:11px;font-weight:800;color:var(--teal)}
.sim-list a{font-size:13.5px;font-weight:600;color:var(--ink);text-decoration:none;line-height:1.45}
.sim-list a:hover{color:var(--teal);text-decoration:underline}
.sim-date{font-size:11px;color:var(--muted)}
/* 공유용 요약 팝업 */
.share-box{max-width:520px}
.share-box textarea{width:100%;font-family:inherit;font-size:13px;line-height:1.6;color:var(--ink);
background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:10px 12px;
margin-bottom:8px;resize:vertical;outline:none}
.share-box textarea:focus{border-color:var(--teal)}
.share-note{font-size:11.5px;color:var(--muted);margin-bottom:12px;min-height:16px}
.share-note.ok{color:#0a7d55;font-weight:700} .share-note.err{color:#b3403a;font-weight:700}
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
/* 해외(영문) 기사 카드 */
.a-orig{font-size:11.5px;color:var(--muted);margin:1px 0 0;line-height:1.4}
.also{font-size:11px;color:var(--muted);margin-top:5px}
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
.hidden{display:none}
"""

RUN_JS = """
(function(){
var GH = window.__GH__ || {};
var KEY = 'fnews_gh_token';
var modal = document.getElementById('tokenModal'), input = document.getElementById('tokenInput');
var keyBtn = document.getElementById('btnKey'), btnD = document.getElementById('btnRun');
if(!btnD) return;
var active = 0, needReload = false;     // 실행 중인 버튼 수 / 국내 실행이 끝나 새로고침이 필요한가

function token(){ try { return localStorage.getItem(KEY); } catch(e){ return null; } }
function setToken(v){ try { localStorage.setItem(KEY, v); } catch(e){} }
function openModal(){ modal.classList.add('show'); input.value = token() || ''; input.focus(); }
function closeModal(){ modal.classList.remove('show'); }
function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }

document.getElementById('tokenCancel').onclick = closeModal;
document.getElementById('tokenSave').onclick = function(){
  var v = input.value.trim();
  if(!v){ return; }
  setToken(v); closeModal(); sayD('토큰이 저장되었습니다', 'ok');
};
keyBtn.onclick = openModal;
input.addEventListener('keydown', function(e){ if(e.key==='Enter') document.getElementById('tokenSave').click(); });

function headers(t){
  return { 'Authorization': 'Bearer ' + t, 'Accept': 'application/vnd.github+json',
           'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': 'application/json' };
}
function api(path){ return 'https://api.github.com/repos/'+GH.owner+'/'+GH.repo+'/actions/workflows/'+path; }

// 실행 버튼 하나를 독립적으로 다루는 러너. 국내·해외가 각자 상태와 진행 확인을 가져서 동시에 눌러도 서로 간섭하지 않는다.
// 진행 확인은 '그 워크플로의' 실행 목록만 본다(전체 목록을 보면 다른 워크플로의 실행을 내 것으로 착각한다).
function makeRunner(btn, statEl, workflow, label, prefix, onSuccess){
  var txt = btn.querySelector('.btn-txt'), running = false;
  function say(msg, cls, link){
    statEl.textContent = msg ? prefix + msg : ''; statEl.className = 'run-status' + (cls ? ' '+cls : '');
    if(msg && link){
      var a = document.createElement('a'); a.href = link.href; a.textContent = link.text; a.className = 'run-link';
      statEl.appendChild(document.createTextNode(' · ')); statEl.appendChild(a);
    }
  }
  function busy(on, lab){ btn.classList.toggle('busy', on); btn.disabled = on; txt.textContent = lab || (on ? label + ' 중' : label); }
  function end(){ running = false; active--; busy(false); }

  async function poll(t, startedAt){
    var url = api(workflow + '/runs') + '?event=workflow_dispatch&per_page=5';
    for(var i=0; i<120; i++){
      await sleep(6000);
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
          end();
          if(run.conclusion === 'success'){ onSuccess(say, el); }
          else { say('실패: ' + (run.conclusion||'error') + ' — GitHub Actions에서 로그 확인', 'err'); }
          return;
        }
        say((run.status === 'queued' ? '대기 중' : '수집 중') + '… ' + el);
      } catch(e){ /* 네트워크 일시 오류는 무시하고 계속 */ }
    }
    end(); say('시간 초과 — GitHub Actions에서 상태를 확인하세요', 'err');
  }

  btn.onclick = async function(){
    if(running) return;
    var t = token();
    if(!t){ openModal(); return; }
    running = true; active++; busy(true, '요청 중'); say('워크플로 실행 요청…');
    try {
      var res = await fetch(api(workflow + '/dispatches'), { method:'POST', headers: headers(t),
                                                            body: JSON.stringify({ ref: GH.branch || 'main' }) });
      if(res.status === 204){
        var startedAt = Date.now();
        busy(true); say('실행 시작됨…');
        poll(t, startedAt);
      } else if(res.status === 401 || res.status === 403){
        end(); say('토큰이 유효하지 않습니다. 토큰 변경을 눌러 다시 입력하세요', 'err'); openModal();
      } else if(res.status === 404){
        end(); say('워크플로를 찾을 수 없습니다 (' + workflow + ')', 'err');
      } else {
        var msg = '';
        try { msg = (await res.json()).message || ''; } catch(e){}
        end(); say('요청 실패 (' + res.status + ') ' + msg, 'err');
      }
    } catch(e){
      end(); say('네트워크 오류: ' + e.message, 'err');
    }
  };
  return say;
}

function reloadWhenIdle(){
  // 국내 실행이 끝났어도 해외가 아직 돌고 있으면 기다린다 — 새로고침하면 해외 쪽 진행 표시가 사라진다
  if(needReload && active === 0){ setTimeout(function(){ location.reload(true); }, 2000); }
}
var sayD = makeRunner(btnD, document.getElementById('runStatus'), GH.workflow, '실행', '', function(say, el){
  needReload = true;
  say(active ? '완료 (' + el + ') · 해외 실행이 끝나면 새로고침합니다' : '완료 (' + el + ') · 새로고침합니다', 'ok');
  reloadWhenIdle();
});
var btnF = document.getElementById('btnRunF');
if(btnF){
  makeRunner(btnF, document.getElementById('runStatusF'), GH.workflow_foreign || 'foreign.yml', '해외 실행', '해외 · ', function(say, el){
    say('완료 (' + el + ')', 'ok', { href: 'foreign.html', text: '해외 영문 보기 →' });
    reloadWhenIdle();
  });
}

if(!token()){ sayD('처음이면 실행을 눌러 토큰을 입력하세요'); }
})();
"""


COPY_JS = """
(function(){
var modal=document.getElementById('shareModal'), ta=document.getElementById('shareText');
var note=document.getElementById('shareNote'), cp=document.getElementById('shareCopy');
if(!modal) return;
var NOTE0='내용을 고친 뒤 복사할 수 있습니다';
function say(msg, cls){ note.textContent=msg; note.className='share-note'+(cls?' '+cls:''); }
function openShare(text){
  ta.value=text; say(NOTE0); cp.textContent='복사';
  modal.classList.add('show'); ta.focus(); ta.select(); ta.scrollTop=0;
}
function closeShare(){ modal.classList.remove('show'); }
function fallback(t){
  var prev=ta.value; ta.value=t; ta.focus(); ta.select();
  var ok=false; try{ ok=document.execCommand('copy'); }catch(e){}
  return ok;
}
function copy(){
  var t=ta.value;
  function done(ok){
    if(ok){ say('클립보드에 복사했습니다', 'ok'); cp.textContent='복사됨 ✓'; }
    else { say('자동 복사가 막혔습니다. 내용을 선택해 Cmd+C(Ctrl+C)로 복사하세요', 'err'); ta.focus(); ta.select(); }
  }
  if(navigator.clipboard && window.isSecureContext){
    navigator.clipboard.writeText(t).then(function(){ done(true); }, function(){ done(fallback(t)); });
  } else { done(fallback(t)); }
}
document.addEventListener('click', function(e){
  var b = e.target.closest ? e.target.closest('.copy-sum') : null;
  if(!b) return;
  e.preventDefault();
  openShare(b.getAttribute('data-copy') || '');
});
cp.addEventListener('click', copy);
document.getElementById('shareClose').addEventListener('click', closeShare);
modal.addEventListener('click', function(e){ if(e.target===modal) closeShare(); });
ta.addEventListener('input', function(){ say(NOTE0); cp.textContent='복사'; });
document.addEventListener('keydown', function(e){
  if(!modal.classList.contains('show')) return;
  if(e.key==='Escape'){ closeShare(); }
  else if(e.key==='Enter' && (e.metaKey||e.ctrlKey)){ e.preventDefault(); copy(); }
});
})();
"""

SIM_JS = """
(function(){
var modal=document.getElementById('simModal'); if(!modal) return;
var list=document.getElementById('simList'), title=document.getElementById('simTitle');
var SIM=window.__SIM__||{};
function close(){ modal.classList.remove('show'); }
function open(id){
  var items=SIM[id]||[]; list.innerHTML='';
  title.textContent='비슷한 기사 '+items.length+'건';
  items.forEach(function(it){
    var li=document.createElement('li');
    var pr=document.createElement('span'); pr.className='sim-press'; pr.textContent=it[0];
    var a=document.createElement('a'); a.textContent=it[1];
    if(it[2]){ a.href=it[2]; a.target='_blank'; a.rel='noopener'; }
    li.appendChild(pr); li.appendChild(a);
    if(it[3]){ var d=document.createElement('span'); d.className='sim-date'; d.textContent=it[3]; li.appendChild(d); }
    list.appendChild(li);
  });
  list.scrollTop=0; modal.classList.add('show');
}
document.addEventListener('click', function(e){
  var b=e.target.closest ? e.target.closest('.sim-btn') : null;
  if(!b) return; e.preventDefault(); open(b.getAttribute('data-sim'));
});
document.getElementById('simClose').addEventListener('click', close);
modal.addEventListener('click', function(e){ if(e.target===modal) close(); });
document.addEventListener('keydown', function(e){ if(e.key==='Escape' && modal.classList.contains('show')) close(); });
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
    var ETC=['regional','policy','nonholding','securities','cardins','etc'];
    var okCo  = (co==='all' || a.dataset.co===co ||
                 (co==='etc' && ETC.indexOf(a.dataset.co)>=0));
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
    // 필터 중엔 매칭 0건인 날짜/회차는 통째로 숨긴다 — 빈 회차를 보여줄 이유가 없다.
    r.classList.toggle('hidden', filtering && vis===0);
    // 필터가 걸리면 매칭된 회차는 자동으로 펼치고(클릭 없이 바로 보이게),
    // 필터를 지우면 기본 상태(최신 회차만 펼침)로 되돌린다.
    r.open = filtering ? (vis>0) : (r.dataset.latest==='1');

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
/*FEED_JS*/
renderSub(); apply(); loadForeign();
})();
"""

# 해외(영문) 기사를 국내 회차 블록과 같은 모양으로 끼워 넣는다. 해외 워크플로가 올린 foreign_feed.json을 열 때마다 읽는다.
#   - 국내 HTML 파일은 바뀌지 않는다(해외 실행과 파일 충돌 없음). 파일이 없거나 실패하면 조용히 건너뛴다.
#   - 외부 기사 문구라 innerHTML을 쓰지 않고 textContent로만 넣는다. 링크는 http(s)만 허용한다.
#   - 카드는 data-co="overseas"라 '전체'와 '해외' 탭에 보이고 다른 탭에서는 숨는다.
FEED_JS = r'''
function fEl(tag, cls, text){ var e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
function fSafe(u){ return /^https?:\/\//i.test(u||'') ? u : '#'; }
function fCard(a){
  var card = fEl('div','article has-sum'); card.dataset.co='overseas'; card.dataset.sector='해외'; card.dataset.type='AI'; card.dataset.foreign='1';
  var day = (a.pub_date||'').slice(0,10).replace(/-/g,'/');
  var lines = (a.summary||'').split('\n').map(function(l){ return l.replace(/^[*\-\u2022\s]+/,'').trim(); }).filter(Boolean);
  var share = [(day ? '['+day+'] ' : '') + a.company].concat(lines.map(function(l){ return '- '+l; }), a.url ? [a.url] : []).join('\n');
  var cp = fEl('button','copy-sum'); cp.type='button'; cp.title='공유용 요약 보기·복사'; cp.setAttribute('aria-label','요약 복사'); cp.setAttribute('data-copy', share); card.appendChild(cp);
  var tags = fEl('div','tags'); tags.appendChild(fEl('span','tag path', a.company+' · 해외')); tags.appendChild(fEl('span','tag ai','영문 번역')); card.appendChild(tags);
  var h = fEl('h3'); var link = fEl('a','', a.title_ko || a.title); link.href=fSafe(a.url); link.target='_blank'; link.rel='noopener'; h.appendChild(link); card.appendChild(h);
  if(a.title_ko) card.appendChild(fEl('div','a-orig', a.title));
  card.appendChild(fEl('div','a-meta', (a.press||'')+' \u00b7 '+(a.pub_date||'').slice(0,16).replace('T',' ')));
  var ul = fEl('ul','summary'); lines.forEach(function(l){ ul.appendChild(fEl('li','',l)); }); card.appendChild(ul);
  if(a.also && a.also.length) card.appendChild(fEl('div','also','함께 다룬 회사: '+a.also.join(', ')));
  var act = fEl('div','card-actions'); var src = fEl('a','src-link','원문 보기 →'); src.href=fSafe(a.url); src.target='_blank'; src.rel='noopener'; act.appendChild(src);
  if(a.dups && a.dups.length){
    var key='f'+a.id; (window.__SIM__ = window.__SIM__ || {})[key] = a.dups.map(function(d){ return [d.press||'', d.title||'', fSafe(d.url) === '#' ? '' : d.url, '']; });
    var sb = fEl('button','sim-btn'); sb.type='button'; sb.setAttribute('data-sim',key); sb.setAttribute('data-n',a.dups.length); sb.title='같은 사건을 다룬 다른 매체 기사'; act.appendChild(sb);
  }
  card.appendChild(act); return card;
}
function fBlock(key, list, latest){
  var d = fEl('details','run-block foreign-run'); d.dataset.latest = latest ? '1' : '0'; d.dataset.ts = key; if(latest) d.open = true;
  var sum = fEl('summary'), head = fEl('div','run-head');
  head.appendChild(fEl('span','dot')); head.appendChild(fEl('h2','', key.replace('T',' ')+' 요청분')); head.appendChild(fEl('span','tag ai','해외 영문'));
  var cnt = fEl('span','cnt', list.length+'건'); cnt.dataset.total = list.length; head.appendChild(cnt);
  head.appendChild(fEl('span','range','영문 매체 · 번역 요약')); head.appendChild(fEl('span','caret','▾'));
  sum.appendChild(head); d.appendChild(sum);
  var body = fEl('div','run-body'); list.forEach(function(a){ body.appendChild(fCard(a)); }); d.appendChild(body); return d;
}
function fBump(c, n){
  var b = coMenu.querySelector('button[data-co="'+c+'"]'); if(!b) return;
  var s = b.querySelector('.n'); if(s) s.textContent = (parseInt(s.textContent,10) || 0) + n;
  if(b.disabled){ b.disabled = false; b.style.opacity = ''; b.style.cursor = ''; }
}
function loadForeign(){
  var box = document.getElementById('runs'); if(!box || !window.fetch) return;
  fetch('foreign_feed.json', {cache:'no-cache'}).then(function(r){ if(!r.ok) throw new Error(r.status); return r.json(); }).then(function(feed){
    var list = (feed && feed.articles) || []; if(!list.length) return;
    var groups = {}, keys = [];
    list.forEach(function(a){ var k=(a.collected_at||'').slice(0,16); if(!k) return; if(!groups[k]){ groups[k]=[]; keys.push(k); } groups[k].push(a); });
    keys.sort().reverse();
    keys.forEach(function(k, i){
      var before = null;
      for(var j=0; j<box.children.length; j++){            // 요청 시각 최신순을 유지하도록 국내 회차 블록 사이에 넣는다
        var c = box.children[j]; if(c.classList.contains('run-block') && (c.dataset.ts||'') < k){ before = c; break; }
      }
      box.insertBefore(fBlock(k, groups[k], i===0), before);
    });
    var n = list.length; fBump('all', n); fBump('overseas', n);
    var arr = (SUBS.overseas = SUBS.overseas || []), f = arr.filter(function(x){ return x[0]==='해외'; })[0];
    if(f) f[1] += n; else arr.push(['해외', n]);
    arts = Array.prototype.slice.call(document.querySelectorAll('.article'));
    arts.forEach(function(a){ a.__txt = a.textContent.toLowerCase(); });
    if(co==='overseas') renderSub();
    apply();
  }).catch(function(){ /* 해외 데이터가 없으면 국내 목록만 보인다 */ });
}
'''
JS = JS.replace("/*FEED_JS*/", FEED_JS)


def _share_text(a, company: str) -> str:
    """카톡 등에 붙여넣어 공유할 요약 문구.

        [2026/10/26] 삼성화재
        - 요약 1줄
        - 요약 2줄
        https://원문링크

    날짜는 기사 게재일, 링크는 언론사 원문(없으면 네이버 링크)이다.
    """
    day = (a["pub_date"] or "")[:10].replace("-", "/")
    head = ("[%s] %s" % (day, company)).strip() if day else company
    lines = ["- " + l.lstrip("*-• ").strip()
             for l in (a["summary"] or "").splitlines() if l.strip()]
    link = a["original_url"] or a["naver_url"] or ""
    return "\n".join([head] + lines + ([link] if link else []))


def _card(a, sim=None, omap=None) -> str:
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
    company = a["company"] or a["subgroup"] or ""
    cls = (" is-ai" if is_ai else "") + (" has-sum" if a["summary"] else "")
    copy_btn = ""
    if a["summary"]:
        share = _share_text(a, company)
        copy_btn = ('<button type="button" class="copy-sum" title="공유용 요약 보기·복사" '
                    'aria-label="요약 복사" data-copy="%s"></button>'
                    % H.escape(share, quote=True).replace("\n", "&#10;"))
    # DB의 press가 비어 있으면 링크의 매체(네이버 oid·도메인)로 outlets.json에서 이름을 채운다
    press_name = a["press"] or outlets.name_for(a["naver_url"] if outlets.key_of(a["naver_url"]) else a["original_url"],
                                                None, omap or {})
    n_sim = len((sim or {}).get(a["id"], ()))
    sim_btn = ('<button type="button" class="sim-btn" data-sim="%d" data-n="%d" '
               'title="같은 사건을 다룬 다른 언론사 기사"></button>' % (a["id"], n_sim)) if n_sim else ""
    return f"""
<div class="article{cls}" data-co="{a['fin_group']}" data-sector="{H.escape(a['sector'] or '기타')}" data-type="{a['dig_ai']}">
 {copy_btn}
 <div class="tags"><span class="tag path">{H.escape(company)} · {H.escape(a['sector'] or '')}</span>
 <span class="tag {'ai' if is_ai else 'digital'}">{a['dig_ai']}</span>{pr_tag}{status}</div>
 <h3><a href="{H.escape(url)}" target="_blank" rel="noopener">{H.escape(a['title'])}</a></h3>
 <div class="a-meta">{H.escape(press_name)} · {pub}</div>
 {summary}
 <div class="kw">매칭 키워드: <b>{H.escape(a['matched_keywords'] or '-')}</b></div>
 <div class="card-actions"><a class="src-link" href="{H.escape(url)}" target="_blank" rel="noopener">원문 보기 →</a>{sim_btn}</div>
</div>"""


def _sector_key(s):
    return SECTOR_ORDER.index(s) if s in SECTOR_ORDER else len(SECTOR_ORDER)


WEEK = "월화수목금토일"


def _fmt_date(d):
    if not d:
        return ""
    return str(d).replace("T", " ")[:16]


def _render_seen_grouped(seen):
    """기열람(직전 회차 이미 반영) 목록 — 원래 게재된 날짜별로 묶어서 보여준다.

    날짜(그 사건이 처음 보도된 날) → 같은 사건(같은 회사·같은 건) 순으로 묶는다.
    회사별로 묶으면 "오늘 KB 기사가 어느 날짜 사건들과 겹쳤는지"는 보이지만
    "어느 날짜에 반복이 몰렸는지"는 안 보인다. 날짜를 1순위로 두면 그게 보인다.
    모든 그룹은 기본으로 펼쳐 둔다(open) — 검수 목적이라 클릭 한 번도 아끼는 게 낫다.
    """
    def esc(x):
        return H.escape(x or "")

    def day_of(d):
        return (str(d)[:10] if d else "날짜미상")

    groups = OrderedDict()  # 날짜 -> {(company,ref) -> {"company":.., "ref":.., "date":.., "items":[]}}
    for a in seen:
        d = day_of(a.get("dup_ref_date"))
        company = a.get("dup_ref_company") or "기타"
        ref = a.get("dup_ref") or "(같은 사건으로 묶인 과거 기사)"
        groups.setdefault(d, OrderedDict())
        key = (company, ref)
        cluster = groups[d].setdefault(key, {"company": company, "ref": ref,
                                              "date": a.get("dup_ref_date"),
                                              "ref_url": a.get("dup_ref_url"),
                                              "items": []})
        cluster["items"].append(a)

    # 최근 날짜부터 (오늘과 가까운 반복이 위로)
    ordered_days = sorted(groups.items(), key=lambda kv: kv[0], reverse=True)

    blocks = []
    for day, clusters in ordered_days:
        total = sum(len(c["items"]) for c in clusters.values())
        cluster_blocks = []
        for c in sorted(clusters.values(), key=lambda c: len(c["items"]), reverse=True):
            ref_url = c.get("ref_url")
            ref_title = esc(c["ref"])
            ref_link = ('<a href="%s" target="_blank">%s</a>' % (esc(ref_url), ref_title)
                       if ref_url else ref_title)
            ref_line = ('<div class="seen-ref"><span class="co">%s</span> · 최초 게재'
                        ' <span class="date">%s</span> · %s</div>'
                        % (esc(c["company"]), esc(_fmt_date(c["date"])), ref_link))
            items = c["items"]
            head = items[0]
            head_url = head.get("naver_url") or ""
            head_t = esc(head.get("title"))
            head_title = ('<a href="%s" target="_blank">%s</a>' % (esc(head_url), head_t)
                          if head_url else head_t)
            head_row = ('<div class="audit-item">%s <span class="meta">· %s · %s</span></div>'
                       % (head_title, esc(head.get("press")), esc(_fmt_date(head.get("pub_date")))))
            rest_rows = []
            for a in items[1:]:
                url = a.get("naver_url") or ""
                t = esc(a.get("title"))
                title = '<a href="%s" target="_blank">%s</a>' % (esc(url), t) if url else t
                rest_rows.append('<div class="audit-item">%s <span class="meta">· %s · %s</span></div>'
                            % (title, esc(a.get("press")), esc(_fmt_date(a.get("pub_date")))))
            # 사건당 대표 기사 하나만 바로 보이고, 나머지 매체는 접어 둔다.
            #   실측: 한 사건에 매체 6~10곳이 그대로 나열돼 화면이 길어졌다.
            if rest_rows:
                more = ('<details class="seen-more"><summary>매체 %d곳 더보기</summary>%s</details>'
                       % (len(rest_rows), "".join(rest_rows)))
            else:
                more = ""
            cluster_blocks.append('<div class="seen-cluster">%s%s%s</div>' % (ref_line, head_row, more))
        blocks.append('<details class="seen-group"><summary>%s — %d건 (%d개 사건)</summary>%s</details>'
                      % (esc(day), total, len(clusters), "".join(cluster_blocks)))

    return ('<div class="audit-grp"><h4>기열람 %d건 (직전 회차에 이미 반영)</h4>%s</div>'
            % (len(seen), "".join(blocks)))


def _audit(screened):
    """1차 통과 기사의 최종 행방 — 중복 제거가 타당했는지 검수."""
    if not screened:
        return ""
    live = [a for a in screened if not a.get("excluded")]
    dup = [a for a in screened if (a.get("exclude_reason") or "").startswith("중복")]
    seen = [a for a in screened if (a.get("exclude_reason") or "").startswith("기열람")]
    irr = [a for a in screened
           if a.get("excluded") and not (a.get("exclude_reason") or "").startswith(("중복", "기열람"))
           and not a.get("dup_members")]

    def item(a, extra=""):
        url = a.get("naver_url") or ""
        t = H.escape(a.get("title") or "")
        title = '<a href="%s" target="_blank">%s</a>' % (H.escape(url), t) if url else t
        return ('<div class="audit-item">%s <span class="meta">· %s</span>%s</div>'
                % (title, H.escape(a.get("press") or ""), extra))

    out = []
    # '반영' 목록은 여기서 보여주지 않는다.
    #   같은 기사가 아래 본문 카드로 이미 전부 나오므로 중복이고,
    #   검수 목록의 목적은 '왜 안 보이는지'를 추적하는 것이다.
    if dup:
        reps = [a for a in screened if a.get("dup_members")]
        # 대표가 최종적으로 반영됐는지 표시한다.
        #   중복 20건을 2개 사건으로 줄여도, 그 대표가 뒤 단계(기열람·검토·요약)에서
        #   또 빠지면 화면엔 아무것도 안 나온다. 반영/미반영을 배지로 구분하고,
        #   미반영은 왜 빠졌는지 사유까지 붙여서 과도 필터링을 바로 알아볼 수 있게 한다.
        blocks = []
        n_live_rep = 0
        for r in reps:
            if not r.get("excluded"):
                n_live_rep += 1
                badge = '<span class="rep-ok">반영됨</span>'
            else:
                why = (r.get("exclude_reason") or "사유 미상")[:44]
                badge = '<span class="rep-out">미반영 · %s</span>' % H.escape(why)
            rows = []
            for m in r["dup_members"]:
                # 옛 회차 데이터는 (제목, 매체, 사유) 3요소 — URL 없이도 동작하게
                t, p, w = m[0], m[1], m[2]
                url = m[3] if len(m) > 3 else ""
                title = ('<a href="%s" target="_blank">%s</a>' % (H.escape(url), H.escape(t))
                         if url else H.escape(t))
                rows.append('<div>└ %s <span class="meta">· %s</span> '
                            '<span class="audit-why">%s</span></div>'
                            % (title, H.escape(p), H.escape(w)))
            # 대표만 바로 보이고, 묶인 기사들은 접어 둔다.
            #   실측: KB국민은행 예금토큰 건 하나에 매체 11곳이 그대로 펼쳐져
            #   화면이 끝없이 길어졌다.
            more = ('<details class="seen-more"><summary>중복 %d건 보기</summary>'
                    '<div class="audit-dup">%s</div></details>'
                    % (len(rows), "".join(rows))) if rows else ""
            blocks.append('%s%s' % (item(r, " " + badge), more))
        if blocks:
            out.append('<div class="audit-grp"><h4>중복 제거 %d건 → %d개 사건 '
                       '(반영 %d · 미반영 %d)</h4>%s</div>'
                       % (len(dup), len(reps), n_live_rep, len(reps) - n_live_rep,
                          "".join(blocks)))
    if seen:
        out.append(_render_seen_grouped(seen))
    if irr:
        # 같은 보도자료가 여러 매체에 실려 반복 제외되는 경우가 많다
        #   (실측: "우리금융, 전북혁신도시 우리원금융타운"이 KBS 등 4개 매체로 중복,
        #    "우리금융 균형발전 전북거점" 계열도 같은 사건).
        #   본문무관 목록 전용 경량 그룹화 — 정식 dedup 로직(cfg 필요)과 별개로,
        #   화면 가독성만을 위해 2글자 이상 단어 겹침으로 느슨하게 묶는다.
        def _loose_tokens(title):
            t = re.sub(r"[\[\]【】\"'“”‘’]", " ", title or "")
            return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", t)}

        irr_tok = [_loose_tokens(a.get("title")) for a in irr]
        clusters, seen_idx = [], set()
        for i, a in enumerate(irr):
            if i in seen_idx:
                continue
            group = [a]
            seen_idx.add(i)
            ca = irr_tok[i]
            for j in range(i + 1, len(irr)):
                if j in seen_idx or not ca:
                    continue
                cb = irr_tok[j]
                if not cb:
                    continue
                sim = len(ca & cb) / min(len(ca), len(cb))
                if sim >= 0.6:
                    group.append(irr[j])
                    seen_idx.add(j)
            clusters.append(group)

        blocks = []
        for g in clusters:
            head_a = g[0]
            reason = H.escape((head_a.get("exclude_reason") or "")[:40])
            if len(g) == 1:
                blocks.append(item(head_a, ' <span class="meta">%s</span>' % reason))
            else:
                members = "".join(
                    '<div>└ %s <span class="meta">· %s</span></div>'
                    % (('<a href="%s" target="_blank">%s</a>'
                        % (H.escape(m.get("naver_url") or ""), H.escape(m.get("title") or ""))
                        if m.get("naver_url") else H.escape(m.get("title") or "")),
                       H.escape(m.get("press") or ""))
                    for m in g[1:])
                blocks.append('%s<details class="seen-more"><summary>중복 %d건 보기</summary>'
                              '<div class="audit-dup">%s</div></details>'
                              % (item(head_a, ' <span class="meta">%s</span>' % reason),
                                 len(g) - 1, members))
        out.append('<div class="audit-grp"><h4>본문 확인 후 제외 %d건 (%d개 사건)</h4>%s</div>'
                   % (len(irr), len(clusters), "".join(blocks)))

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
           screened_rows=None, similar=None, omap=None):
    global GH_CONF
    GH_CONF = gh or {}
    runs = OrderedDict()
    counts = {k: 0 for k in MENU_LABELS}
    subs = {}          # menu_id -> {company: count}
    # 탭 옆 숫자·활성화 여부는 아카이브 전체(60일치) 기준으로 집계한다.
    #   과거엔 '가장 최근 실행'분만 셌는데, 그러면 이번 회차에 기사가 없던
    #   회사 탭이 disabled로 막혀 과거 회차에 있는 기사조차 필터로 못 봤다.
    for a in rows:
        runs.setdefault(a["run_id"], {"meta": a, "arts": []})["arts"].append(a)
        counts["all"] += 1
        # 지방·국책·비지주·미분류는 '기타' 탭으로 합산
        grp = "etc" if a["fin_group"] in ETC_GROUPS else a["fin_group"]
        counts[grp] = counts.get(grp, 0) + 1
        sec = a["sector"] or "기타"
        subs.setdefault(grp, {})
        subs[grp][sec] = subs[grp].get(sec, 0) + 1

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
        for k, v in MENU_LABELS.items())

    # 해외 영문 페이지(foreign.html)는 해외 트랙 워크플로가 만든다. 파일이 있을 때만 링크를 건다.
    f_link = ('<a class="f-link" href="foreign.html" title="해외 금융사 영문 기사 요약 (별도 페이지)">해외 영문 ↗</a>'
              if os.path.exists(os.path.join(os.path.dirname(out_path) or ".", "foreign.html")) else "")

    import json
    subs_json = json.dumps(sub_js, ensure_ascii=False)
    runlog = _runlog(history or [])
    audit = _audit(screened_rows or [])
    gh_json = json.dumps(GH_CONF, ensure_ascii=False)
    # 비슷한 기사 목록은 카드마다 넣지 않고 한 번만 싣는다. </script> 조기 종료를 막기 위해 '</'를 이스케이프.
    sim_json = json.dumps({str(k): [list(x) for x in v] for k, v in (similar or {}).items()},
                          ensure_ascii=False).replace("</", "<\\/")

    run_html = ""
    for i, (rid, r) in enumerate(runs.items()):
        m = r["meta"]
        req = (m["run_requested"] or "")[:16].replace("T", " ")
        rng = "검색 %s ~ %s" % ((m["run_start"] or "")[5:16].replace("T", " "),
                               (m["run_end"] or "")[5:16].replace("T", " "))
        # 발행일 최신순 정렬 (pub_date 내림차순)
        blocks = "".join(_card(a, similar, omap) for a in sorted(
            r["arts"], key=lambda x: (x["pub_date"] or ""), reverse=True))
        # 최신 회차만 펼침, 과거 요청분은 접어둠
        is_latest = (i == 0)
        opened = " open" if is_latest else ""
        label = f"{req} 요청분" + ("" if is_latest else " (과거)")
        run_html += f"""
<details class="run-block" data-latest="{1 if is_latest else 0}" data-ts="{(m['run_requested'] or '')[:16]}"{opened}>
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
        # 하단 '이번 회차 제외 목록'은 제거 — 위쪽 1차 통과 검수 목록과 내용이 겹친다.
        _ = items
        ex_html = ""

    s = run_stats
    warn = []
    if s.get("cutoff_keywords"):
        warn.append("절단: %s" % H.escape(s["cutoff_keywords"][:60]))
    if s.get("truncated_from"):
        warn.append("72h 초과 잘림: %s 이전" % s["truncated_from"][:16])
    # 보도자료(PR) 크롤링 실패는 화면에 표기하지 않는다 — 상시 노출돼 노이즈만 된다.
    # 실행 로그에는 그대로 남으므로 진단은 로그에서 한다.
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
<title>금융권 디지털 AI 동향</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/pretendard/1.3.9/static/pretendard.min.css">
<style>{CSS}</style></head><body>
<header><div class="eyebrow">Financial Digital · AI News Archive</div>
<h1>금융권 디지털 AI 동향</h1>
<div class="gen-meta">최종 갱신 {s.get("generated_at","")} · 보관 60일 · 뉴스(네이버 API) + 보도자료(9개 그룹)</div></header>
<div class="run-bar">
  <button class="btn-run" id="btnRun" title="국내 뉴스 수집"><span class="spin"></span><span class="btn-txt">실행</span></button>
  <button class="btn-run btn-run-f" id="btnRunF" title="해외(영문) 뉴스 수집 — 국내와 별도로 동시에 돌릴 수 있음"><span class="spin"></span><span class="btn-txt">해외 실행</span></button>
  <button class="btn-key" id="btnKey">토큰 변경</button>
</div>
<div class="run-stats"><span class="run-status" id="runStatus"></span><span class="run-status" id="runStatusF"></span></div>
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
<div class="modal" id="shareModal">
  <div class="modal-box share-box">
    <h3>공유용 요약</h3>
    <textarea id="shareText" rows="9" spellcheck="false"></textarea>
    <div class="share-note" id="shareNote">내용을 고친 뒤 복사할 수 있습니다</div>
    <div class="modal-btns">
      <button id="shareClose">닫기</button>
      <button class="primary" id="shareCopy">복사</button>
    </div>
  </div>
</div>
<div class="modal" id="simModal">
  <div class="modal-box sim-box">
    <h3 id="simTitle">비슷한 기사</h3>
    <div class="sim-note">같은 사건을 다룬 다른 언론사 기사입니다. 중복으로 판단돼 카드로는 나타나지 않은 기사이며, 제목을 누르면 원문이 열립니다.</div>
    <ul class="sim-list" id="simList"></ul>
    <div class="modal-btns"><button id="simClose">닫기</button></div>
  </div>
</div>
{runlog}
<div class="sticky">
  <nav class="company-menu" id="menu">{menu}{f_link}</nav>
  <nav class="sub-menu hidden" id="submenu"></nav>
  <div class="search-wrap">
    <svg class="ico" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
    <input type="search" id="q" placeholder="제목·요약·회사명 검색" autocomplete="off">
    <button class="clr" id="clr" aria-label="지우기">×</button>
  </div>
  <div class="search-hits" id="hits"></div>
</div>
<div id="runs">{run_html}</div>
{ex_html}
<footer>금융 디지털·AI 뉴스 수집 시스템 v2.5 — 수집은 넓게, 판단은 본문 확보 후 로컬에서</footer>
<script>window.__SUBS__ = {subs_json}; window.__GH__ = {gh_json}; window.__SIM__ = {sim_json};</script>
<script>{RUN_JS}</script>
<script>{COPY_JS}</script>
<script>{SIM_JS}</script>
<script>{JS}</script></body></html>"""

    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(doc)
    os.replace(tmp, out_path)
    return out_path
