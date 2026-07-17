"""목록 보기 생성 — 날짜 / 회사 / 제목 을 한 행씩

카드 형식 아카이브(financial_news_archive.html)와 별개로,
과거 기사를 빠르게 훑어보기 위한 압축 목록을 만든다.

사용:  python list_view.py           (60일)
       python list_view.py 14        (최근 14일만)

결과:  output/article_list.html
       VS Code에서 우클릭 → Show Preview 로 보면 편하다.
"""
import html as H
import sys
from collections import OrderedDict

import yaml

import db as dbm

CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1c1c1a;--muted:#6b6b66;--line:#e5e3dd;
--teal:#0d7377;--navy:#2c3e50;--hl:#fff3b8}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Pretendard',sans-serif;
background:var(--bg);color:var(--ink);padding:18px;font-size:13px;line-height:1.5}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:17px;font-weight:800;margin-bottom:3px}
.sub{font-size:12px;color:var(--muted);margin-bottom:14px}
.tools{display:flex;gap:8px;align-items:center;margin-bottom:14px;position:sticky;top:0;
background:var(--bg);padding:8px 0;z-index:5;border-bottom:1px solid var(--line)}
#q{flex:1;font-family:inherit;font-size:13px;border:1px solid var(--line);border-radius:7px;
padding:8px 12px;outline:none;background:var(--card)}
#q:focus{border-color:var(--teal)}
#cnt{font-size:12px;color:var(--muted);white-space:nowrap}
.day{margin-bottom:18px}
.day h2{font-size:13px;font-weight:800;color:var(--teal);padding:6px 0;
border-bottom:1.5px solid var(--teal);margin-bottom:2px;display:flex;justify-content:space-between}
.day h2 span{font-weight:600;color:var(--muted);font-size:11.5px}
.row{display:grid;grid-template-columns:112px 1fr 62px;gap:10px;align-items:baseline;
padding:5px 4px;border-bottom:1px solid var(--line)}
.row:hover{background:var(--card)}
.co{font-size:11.5px;font-weight:700;color:var(--navy);white-space:nowrap;overflow:hidden;
text-overflow:ellipsis}
.ti a{color:var(--ink);text-decoration:none}
.ti a:hover{color:var(--teal);text-decoration:underline}
.tag{font-size:10px;font-weight:700;text-align:right;white-space:nowrap}
.tag.ai{color:var(--navy)} .tag.dg{color:var(--teal)}
.no-sum{color:#b3403a;font-weight:600;font-size:10px}
mark{background:var(--hl);padding:0 1px}
.empty{text-align:center;color:var(--muted);padding:30px;font-size:12.5px}
@media(max-width:640px){.row{grid-template-columns:90px 1fr;gap:8px}.tag{display:none}}
"""

JS = """
(function(){
var q=document.getElementById('q'),cnt=document.getElementById('cnt');
var rows=[].slice.call(document.querySelectorAll('.row'));
var days=[].slice.call(document.querySelectorAll('.day'));
rows.forEach(function(r){r.dataset.t=r.textContent.toLowerCase();});
function esc(s){return s.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');}
function run(){
  var v=q.value.trim().toLowerCase(), n=0;
  rows.forEach(function(r){
    var hit = !v || r.dataset.t.indexOf(v)>-1;
    r.style.display = hit ? '' : 'none';
    if(hit) n++;
    var ti=r.querySelector('.ti');
    var raw=ti.dataset.raw || (ti.dataset.raw=ti.innerHTML);
    ti.innerHTML = (v && hit) ? raw.replace(new RegExp('('+esc(v)+')','ig'),'<mark>$1</mark>') : raw;
  });
  days.forEach(function(d){
    var vis=[].slice.call(d.querySelectorAll('.row')).some(function(r){return r.style.display!=='none';});
    d.style.display = vis ? '' : 'none';
  });
  cnt.textContent = v ? n+'건 검색됨' : rows.length+'건';
}
q.addEventListener('input',run); run();
})();
"""


def build(rows) -> str:
    by_day = OrderedDict()
    for a in rows:
        d = (a["pub_date"] or "")[:10] or "날짜 미상"
        by_day.setdefault(d, []).append(a)

    blocks = []
    for d in sorted(by_day, reverse=True):
        arts = sorted(by_day[d], key=lambda x: (x["company"] or "", x["title"] or ""))
        lines = []
        for a in arts:
            url = a["naver_url"] or a["original_url"] or ""
            t = H.escape(a["title"] or "")
            title = ('<a href="%s" target="_blank">%s</a>' % (H.escape(url), t)) if url else t
            if not a["summary_ok"]:
                title += ' <span class="no-sum">[요약없음]</span>'
            dg = a["dig_ai"] or ""
            cls = "ai" if dg == "AI" else "dg"
            lines.append(
                '<div class="row"><div class="co">%s</div>'
                '<div class="ti">%s</div><div class="tag %s">%s</div></div>'
                % (H.escape(a["company"] or "-"), title, cls, H.escape(dg)))
        blocks.append(
            '<div class="day"><h2>%s <span>%d건</span></h2>%s</div>'
            % (d, len(arts), "".join(lines)))

    body = "".join(blocks) or '<div class="empty">기사가 없습니다.</div>'
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>기사 목록</title><style>{CSS}</style></head><body><div class="wrap">
<h1>기사 목록</h1>
<div class="sub">날짜 · 회사 · 제목 — 제목을 누르면 원문으로 이동</div>
<div class="tools"><input id="q" placeholder="회사명·제목 검색" autocomplete="off">
<span id="cnt"></span></div>
{body}
</div><script>{JS}</script></body></html>"""


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    days = int(sys.argv[1]) if len(sys.argv) > 1 else cfg["db"]["retention_days"]
    conn = dbm.connect(cfg["db"]["path"])
    rows = dbm.get_archive_articles(conn, days)
    out = "output/article_list.html"
    with open(out, "w", encoding="utf-8") as fp:
        fp.write(build(rows))
    print(f"{len(rows)}건 → {out}")
    print("VS Code에서 우클릭 → Show Preview")


if __name__ == "__main__":
    main()
