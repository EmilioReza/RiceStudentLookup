#!/usr/bin/env python3
"""Local browser UI for reviewing uncertain Rice directory records."""

import argparse
import csv
import hashlib
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


GRADES = ("Freshman", "Sophomore", "Junior", "Senior")
FIELDS = ("name", "college", "affiliation", "matriculation_term", "major", "email", "phone", "department", "office", "college_page")


def person_key(record):
    value = "|".join(str(record.get(field, "")) for field in ("name", "college", "email", "matriculation_term"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class ReviewStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.lock = threading.Lock()

    def path(self, name):
        return self.data_dir / name

    def load(self):
        review = read_json(self.path("review_people.json"), read_json(self.path("flagged_people.json"), []))
        people = read_json(self.path("rice_people.json"), [])
        removed = read_json(self.path("removed_people.json"), [])
        decisions = read_json(self.path("review_decisions.json"), {})
        visible = [record for record in review if decisions.get(person_key(record), {}).get("action") != "skipped"]
        return people, review, removed, decisions, visible

    def save_json(self, name, value):
        self.path(name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def save_people_csv(self, people):
        columns = ["name", "college", "phone", "affiliation", "calculated_grade", "matriculation_term", "major", "address", "email", "college_page"]
        columns += sorted({key for record in people for key in record} - set(columns))
        with self.path("rice_people.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(people)

    def update_metadata(self, people, review, removed):
        metadata = read_json(self.path("scrape_metadata.json"), {})
        metadata.update({
            "exported_person_count": len(people),
            "flagged_person_count": len(review),
            "review_person_count": len(review),
            "removed_person_count": len(removed),
        })
        self.save_json("scrape_metadata.json", metadata)

    def apply(self, key, action, grade=None):
        with self.lock:
            people, review, removed, decisions, _ = self.load()
            match = next((record for record in review if person_key(record) == key), None)
            if match is None:
                raise ValueError("That record is no longer in the review queue.")
            now = datetime.now(timezone.utc).isoformat()
            if action == "skip":
                decisions[key] = {"action": "skipped", "updated_at_utc": now}
            elif action == "exclude":
                review = [record for record in review if person_key(record) != key]
                excluded = dict(match)
                excluded.pop("review_priority", None)
                excluded.pop("possible_reason", None)
                excluded["removal_reason"] = "manually excluded during review"
                removed.append(excluded)
                decisions.pop(key, None)
            elif action == "grade":
                if grade not in GRADES:
                    raise ValueError("Choose a valid grade.")
                review = [record for record in review if person_key(record) != key]
                graded = dict(match)
                graded.pop("review_priority", None)
                graded.pop("possible_reason", None)
                graded["calculated_grade"] = grade
                people.append(graded)
                decisions.pop(key, None)
            else:
                raise ValueError("Unknown review action.")
            self.save_json("rice_people.json", people)
            self.save_json("review_people.json", review)
            self.save_json("flagged_people.json", review)
            self.save_json("removed_people.json", removed)
            self.save_json("review_decisions.json", decisions)
            self.save_people_csv(people)
            self.update_metadata(people, review, removed)
            return len(people), len(review), len(removed)


HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rice Directory Review</title>
<style>
:root{--ink:#17221d;--muted:#68756e;--paper:#f5f3ed;--panel:#fffdf8;--line:#d8ddd5;--accent:#c84b31;--accent-dark:#87301f;--teal:#176b68}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 10% 0%,#e3ece4 0 18%,transparent 40%),var(--paper);color:var(--ink);font:15px/1.5 Georgia,serif}
header{padding:34px max(22px,calc((100% - 1100px)/2)) 24px;border-bottom:1px solid var(--line)}
.kicker{color:var(--accent);font:700 12px/1.2 ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase}.title{display:flex;justify-content:space-between;gap:20px;align-items:end}.title h1{font-size:clamp(30px,5vw,58px);line-height:1;margin:10px 0 0;font-weight:400}.count{font:700 24px ui-monospace,monospace;color:var(--teal);white-space:nowrap}
main{max-width:1100px;margin:0 auto;padding:24px 22px 70px}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:22px}.toolbar input,.toolbar select{border:1px solid var(--line);background:var(--panel);padding:11px 13px;font:inherit}.toolbar input{flex:1;min-width:220px}.status{color:var(--muted);font-size:14px}
.card{background:var(--panel);border:1px solid var(--line);box-shadow:0 10px 30px #25382b0d;display:none}.card.active{display:block}.card-head{padding:24px 26px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:20px}.card h2{font-size:31px;line-height:1.1;margin:0 0 7px;font-weight:400}.reason{color:var(--accent-dark);font-size:14px}.priority{color:var(--teal);font:700 11px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.08em}.details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 25px;padding:8px 26px}.detail{padding:12px 0;border-bottom:1px solid #e8ebe5}.label{display:block;color:var(--muted);font:700 11px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.06em}.value{overflow-wrap:anywhere}.actions{display:flex;flex-wrap:wrap;gap:10px;padding:22px 26px;background:#f0f3ed;border-top:1px solid var(--line)}button{border:1px solid var(--ink);background:var(--ink);color:white;padding:11px 16px;font:700 14px ui-monospace,monospace;cursor:pointer}button:hover{background:var(--teal)}button.secondary{background:var(--panel);color:var(--ink)}button.danger{background:var(--accent);border-color:var(--accent)}button:disabled{opacity:.5;cursor:wait}.grade{padding:10px;border:1px solid var(--ink);background:white;font:inherit}.empty{display:none;padding:40px 10px;text-align:center;color:var(--muted);font-size:20px}.error{color:var(--accent);margin:12px 0}.progress{height:4px;background:var(--line);margin:0 0 22px}.bar{height:100%;background:var(--accent);width:0;transition:width .2s}
@media(max-width:650px){.title{display:block}.count{display:block;margin-top:16px}.details{grid-template-columns:1fr}.card-head{padding:20px}.details,.actions{padding-left:20px;padding-right:20px}.card h2{font-size:26px}}
</style></head>
<body><header><div class="kicker">Rice University · directory cleanup</div><div class="title"><h1>Review the uncertain records</h1><div class="count" id="count">Loading...</div></div></header>
<main><div class="toolbar"><input id="search" placeholder="Search names, colleges, majors..." autocomplete="off"><select id="priority"><option value="all">All priorities</option><option value="high">High priority</option><option value="medium">Medium priority</option></select><span class="status" id="status"></span></div><div class="progress"><div class="bar" id="bar"></div></div><div id="error" class="error"></div><section id="card" class="card"><div class="card-head"><div><h2 id="name"></h2><div class="reason" id="reason"></div></div><div class="priority" id="priorityLabel"></div></div><div class="details" id="details"></div><div class="actions"><button id="copy">Copy name + info</button><button class="secondary" id="skip">Skip for now</button><select class="grade" id="grade"><option value="">Set calculated grade...</option><option>Freshman</option><option>Sophomore</option><option>Junior</option><option>Senior</option></select><button id="setGrade">Set grade</button><button class="danger" id="exclude">Exclude</button></div></section><div class="empty" id="empty">No records match this view.</div></main>
<script>
const state={records:[],index:0,visible:[]};
const $=id=>document.getElementById(id);
function visible(){const q=$('search').value.toLowerCase(), p=$('priority').value;state.visible=state.records.filter(r=>(p==='all'||r.review_priority===p)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));state.index=Math.min(state.index,state.visible.length-1);render()}
function render(){const r=state.visible[state.index], total=state.visible.length;$('count').textContent=total?`${state.index+1} / ${total}`:'0 records';$('status').textContent=`${state.records.length} remaining in review`;$('bar').style.width=total?`${(state.index+1)/total*100}%`:'0%';$('card').classList.toggle('active',!!r);$('empty').style.display=r?'none':'block';if(!r)return;$('name').textContent=r.name||'Unnamed record';$('reason').textContent=r.possible_reason||'Review record';$('priorityLabel').textContent=r.review_priority||'';const hidden=new Set(['name','possible_reason','review_priority']);$('details').innerHTML=Object.entries(r).filter(([k,v])=>!hidden.has(k)&&v!==''&&v!=null).map(([k,v])=>`<div class="detail"><span class="label">${k.replaceAll('_',' ')}</span><span class="value"></span></div>`).join('');[...$('details').querySelectorAll('.value')].forEach((el,i)=>el.textContent=Object.entries(r).filter(([k,v])=>!hidden.has(k)&&v!==''&&v!=null)[i][1])}
async function action(type){const r=state.visible[state.index];if(!r)return;const grade=$('grade').value;if(type==='grade'&&!grade){$('error').textContent='Choose a grade first.';return}document.querySelectorAll('button,select').forEach(x=>x.disabled=true);$('error').textContent='';try{const res=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:r._key,action:type,grade})});const data=await res.json();if(!res.ok)throw new Error(data.error||'Action failed');state.records=state.records.filter(x=>x._key!==r._key);state.index=Math.min(state.index,state.records.length-1);$('grade').value='';visible()}catch(e){$('error').textContent=e.message}finally{document.querySelectorAll('button,select').forEach(x=>x.disabled=false)}}
async function copy(){const r=state.visible[state.index];const text=Object.entries(r).filter(([k,v])=>k!=='_key'&&v!==''&&v!=null).map(([k,v])=>`${k.replaceAll('_',' ')}: ${v}`).join('\n');await navigator.clipboard.writeText(text);$('status').textContent='Copied name and listed info'}
async function load(){try{const res=await fetch('/api/records');state.records=(await res.json()).records;visible()}catch(e){$('error').textContent=e.message}}
$('search').oninput=visible;$('priority').onchange=visible;$('copy').onclick=copy;$('skip').onclick=()=>action('skip');$('exclude').onclick=()=>action('exclude');$('setGrade').onclick=()=>action('grade');load();
</script></body></html>'''


def handler_factory(store):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, value, status=200):
            payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if urlparse(self.path).path == "/api/records":
                _, _, _, _, visible = store.load()
                self.send_json({"records": [dict(record, _key=person_key(record)) for record in visible]})
            else:
                payload = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def do_POST(self):
            if urlparse(self.path).path != "/api/action":
                self.send_json({"error": "Not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length))
                counts = store.apply(body["key"], body["action"], body.get("grade"))
                self.send_json({"counts": counts})
            except (KeyError, ValueError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, 400)

        def log_message(self, format, *args):
            return

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_factory(ReviewStore(args.data_dir)))
    print(f"Review UI: http://127.0.0.1:{args.port}")
    print(f"Data directory: {args.data_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()