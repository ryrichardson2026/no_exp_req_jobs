"""runlog.py - one durable, structured record per run + a local dashboard.

Every run_pull.py run (COMPLETE or PARTIAL) emits ONE record, so the per-run
artifacts that today live in a lot of places - the UTF-16 tee log, movement_*.txt,
applicable_report.txt, prerender/out/_lifecycle.json, the Supabase `pulls` row, the
Vercel deploy - collapse into a single row the dashboard reads.

Storage is BOTH (operator's choice): out/runs/ locally (always) AND a Supabase
`pipeline_runs` row (best-effort mirror). A mirror failure NEVER breaks the pull;
the local copy is authoritative and the dashboard reads only local data.

The dashboard is a self-contained local HTML file, regenerated every run. It EMBEDS
the run history inline (no fetch - it opens from file://, where fetch is blocked).

Everything here is defensive and additive: emit() swallows its own errors so a
logging fault can never sink the pull or the publish. Python stdlib only.
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(HERE, "out", "runs")
INDEX = os.path.join(RUNS_DIR, "index.jsonl")
DASHBOARD = os.path.join(RUNS_DIR, "dashboard.html")
KEEP = 120          # runs retained in the index + embedded in the dashboard

SUPABASE_URL = (os.environ.get("SUPABASE_URL")
                or "https://eyatyzatcmjnmazmaghd.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Columns the Supabase mirror sends. Must match the pipeline_runs table (created in
# Supabase, not git - see the module that owns migrations). tenants/halts ride as jsonb.
_MIRROR_COLUMNS = (
    "stamp", "ran_at", "status", "severity", "published", "publish_status", "deploy_url",
    "total_applicable", "baseline_applicable", "applicable_delta",
    "movement_pct", "worst_employer", "worst_employer_pct",
    "bake_job_pages", "bake_listing_views", "live_jobs", "expired_jobs",
    "git_head", "halts", "tenants",
)


def iso_from_stamp(stamp):
    """20260910T141043Z -> 2026-09-10T14:10:43+00:00 (for a real timestamptz)."""
    try:
        return (datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
                .replace(tzinfo=timezone.utc).isoformat())
    except Exception:
        return None


# --------------------------------------------------------------------------
# local store: out/runs/run_<stamp>.json (archive) + index.jsonl (the dashboard feed)
# --------------------------------------------------------------------------

def _read_index():
    if not os.path.exists(INDEX):
        return []
    out = []
    with open(INDEX, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def write_local(record):
    os.makedirs(RUNS_DIR, exist_ok=True)
    with open(os.path.join(RUNS_DIR, f"run_{record['stamp']}.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    # Rewrite the index: prior runs (minus any same-stamp re-run) + this one, newest last,
    # capped at KEEP. One full record per line - small (~a few KB) and the dashboard drill-down
    # needs the per-tenant detail, so there is no separate "summary" projection to drift.
    runs = [r for r in _read_index() if r.get("stamp") != record["stamp"]]
    runs.append(record)
    runs = runs[-KEEP:]
    with open(INDEX, "w", encoding="utf-8") as fh:
        for r in runs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return runs


# --------------------------------------------------------------------------
# Supabase mirror (best-effort; never fatal)
# --------------------------------------------------------------------------

def mirror_supabase(record):
    """Upsert one pipeline_runs row (on_conflict=stamp). Returns a status string; never
    raises. No service key / no table / network fault -> a one-line note, run continues."""
    if not SERVICE_KEY:
        return "skipped (no SUPABASE_SERVICE_ROLE_KEY)"
    row = {c: record.get(c) for c in _MIRROR_COLUMNS}
    body = json.dumps([row]).encode("utf-8")
    url = SUPABASE_URL + "/rest/v1/pipeline_runs?on_conflict=stamp"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("apikey", SERVICE_KEY)
    req.add_header("Authorization", "Bearer " + SERVICE_KEY)
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "resolution=merge-duplicates,return=minimal")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30):
                return "mirrored"
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:160]
            return f"mirror skipped (HTTP {e.code}: {detail})"
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1)); continue
            return f"mirror skipped (network: {e})"


# --------------------------------------------------------------------------
# dashboard (self-contained local HTML, data embedded inline)
# --------------------------------------------------------------------------

def render_dashboard(runs, generated_iso):
    os.makedirs(RUNS_DIR, exist_ok=True)
    html = (_TEMPLATE
            .replace("__RUNS_JSON__", json.dumps(runs, ensure_ascii=False))
            .replace("__GENERATED__", generated_iso or ""))
    with open(DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(html)
    return DASHBOARD


def emit(record):
    """The one call run_pull makes. Local write is authoritative; the Supabase mirror and
    the render are wrapped so neither can break the run. Returns (dashboard_path, mirror_note)."""
    runs = write_local(record)
    mirror_note = "skipped"
    try:
        mirror_note = mirror_supabase(record)
    except Exception as e:                       # belt-and-suspenders: mirror is never fatal
        mirror_note = f"mirror error ({type(e).__name__})"
    render_dashboard(runs, datetime.now(timezone.utc).isoformat())
    return DASHBOARD, mirror_note


# The page is written against CSS custom-property "roles" (dataviz palette): status colors
# are fixed (good/warning/critical), the trend line is the sequential-blue series, and both
# light and dark are selected (dark is not an auto-flip). Single series -> no legend on the
# line; the status legend labels the dots so state is never color-alone.
_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NoProbJobs · Pipeline Runs</title>
<style>
  :root{
    --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
    --series:#2a78d6; --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
    --good-ink:#006300;
  }
  @media (prefers-color-scheme: dark){:root{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --series:#3987e5; --good-ink:#0ca30c;
  }}
  :root[data-theme="light"]{
    --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --grid:#e1e0d9;
    --axis:#c3c2b7; --border:rgba(11,11,11,.10); --series:#2a78d6; --good-ink:#006300;
  }
  :root[data-theme="dark"]{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --grid:#2c2c2a;
    --axis:#383835; --border:rgba(255,255,255,.10); --series:#3987e5; --good-ink:#0ca30c;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45;
    -webkit-font-smoothing:antialiased}
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 64px}
  header{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
  h1{font-size:20px;margin:0;letter-spacing:-.01em}
  .gen{color:var(--muted);font-size:12.5px}
  .themebtn{margin-left:12px;border:1px solid var(--border);background:var(--surface);
    color:var(--ink2);border-radius:6px;padding:4px 9px;font-size:12px;cursor:pointer}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px}
  .hero{margin-top:18px;display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap}
  .badge{display:inline-flex;align-items:center;gap:8px;font-weight:700;font-size:13px;
    padding:6px 12px;border-radius:999px;white-space:nowrap}
  .dot{width:9px;height:9px;border-radius:50%;flex:none}
  .b-good{background:color-mix(in srgb,var(--good) 16%,transparent);color:var(--good-ink)}
  .b-warning{background:color-mix(in srgb,var(--warning) 22%,transparent);color:var(--ink)}
  .b-critical{background:color-mix(in srgb,var(--critical) 18%,transparent);color:var(--critical)}
  .g-good{background:var(--good)} .g-warning{background:var(--warning)} .g-critical{background:var(--critical)}
  .herotext{flex:1;min-width:240px}
  .herotext .when{color:var(--ink2);font-size:13px;margin-top:8px}
  .herotext .pub{margin-top:6px;font-size:13px}
  .herotext a{color:var(--series);text-decoration:none} .herotext a:hover{text-decoration:underline}
  .tiles{margin-top:16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
  .tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
  .tile .k{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}
  .tile .v{font-size:26px;font-weight:650;margin-top:4px;letter-spacing:-.02em}
  .tile .d{font-size:12.5px;margin-top:2px;color:var(--ink2)}
  .up{color:var(--good-ink)} .down{color:var(--critical)}
  section.block{margin-top:26px}
  section.block h2{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);
    margin:0 0 10px;font-weight:650}
  .chartwrap{position:relative;background:var(--surface);border:1px solid var(--border);
    border-radius:12px;padding:14px 8px 6px}
  svg{display:block;width:100%;height:auto;overflow:visible}
  .legend{display:flex;gap:16px;flex-wrap:wrap;margin:8px 4px 2px;font-size:12px;color:var(--ink2)}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .tip{position:absolute;pointer-events:none;background:var(--surface);border:1px solid var(--border);
    border-radius:8px;padding:7px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.14);
    opacity:0;transition:opacity .08s;white-space:nowrap;color:var(--ink)}
  .tip b{font-variant-numeric:tabular-nums}
  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{text-align:left;color:var(--muted);font-weight:600;font-size:11.5px;
    text-transform:uppercase;letter-spacing:.03em;padding:8px 10px;border-bottom:1px solid var(--border)}
  tbody td{padding:9px 10px;border-bottom:1px solid var(--border);vertical-align:top}
  tbody tr.run{cursor:pointer}
  tbody tr.run:hover{background:color-mix(in srgb,var(--series) 7%,transparent)}
  .num{font-variant-numeric:tabular-nums}
  .pill{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;
    padding:3px 9px;border-radius:999px}
  .detail td{background:color-mix(in srgb,var(--series) 4%,transparent)}
  .detail table{margin:2px 0 2px}
  .detail .flag-FLAG,.detail .flag-FAIL{color:var(--critical);font-weight:600}
  .halts{margin:8px 0 0;padding-left:18px;color:var(--critical)}
  .halts li{margin:2px 0}
  .empty{color:var(--muted);padding:30px 0;text-align:center}
  .subtle{color:var(--muted);font-size:12px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div><h1>NoProbJobs · Pipeline Runs</h1></div>
    <div class="gen">generated <span id="gen"></span>
      <button class="themebtn" id="theme">theme</button></div>
  </header>
  <div id="app"></div>
</div>
<script>
const RUNS = __RUNS_JSON__;
const GENERATED = "__GENERATED__";

const SEV = {good:{cls:"good",label:"OK"},warning:{cls:"warning",label:"Partial"},critical:{cls:"critical",label:"Failed"}};
const fmt = n => (n===null||n===undefined||n==="")?"–":Number(n).toLocaleString();
const signed = n => (n>0?"+":"")+Number(n).toLocaleString();
function when(iso){ if(!iso) return "–"; const d=new Date(iso);
  return d.toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}); }
function ago(iso){ if(!iso) return ""; const s=(Date.now()-new Date(iso))/1000;
  if(s<3600) return Math.round(s/60)+"m ago"; if(s<86400) return Math.round(s/3600)+"h ago";
  return Math.round(s/86400)+"d ago"; }

document.getElementById("gen").textContent = when(GENERATED);

// theme toggle (prefers-color-scheme is the default; the button stamps data-theme)
const root=document.documentElement;
document.getElementById("theme").onclick=()=>{
  const cur=root.getAttribute("data-theme");
  const sysDark=matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme", cur? (cur==="dark"?"light":"dark") : (sysDark?"light":"dark"));
  draw();
};

const app=document.getElementById("app");
if(!RUNS.length){ app.innerHTML='<div class="empty">No runs recorded yet. The next <code>run_pull.py</code> run writes the first record here.</div>'; }
else render();

function render(){
  const byTime=[...RUNS].sort((a,b)=>(a.ran_at||"").localeCompare(b.ran_at||""));
  const latest=byTime[byTime.length-1];
  const sev=SEV[latest.severity]||SEV.warning;
  const bake=latest.bake_job_pages!=null? `${fmt(latest.bake_job_pages)} pages · ${fmt(latest.bake_listing_views)} views`:"–";
  const pub = latest.published
      ? `Published — <a href="${latest.deploy_url||"#"}" target="_blank" rel="noopener">${(latest.deploy_url||"").replace(/^https?:\/\//,"")||"deploy"}</a>`
      : `Not published — ${latest.publish_status||"–"}`;
  const dAppl=latest.applicable_delta;
  app.innerHTML = `
    <div class="hero card">
      <span class="badge b-${sev.cls}"><span class="dot g-${sev.cls}"></span>${latest.status}${latest.severity==="critical"?" · "+(latest.publish_status||"failed"):""}</span>
      <div class="herotext">
        <div class="when">Last run ${when(latest.ran_at)} · ${ago(latest.ran_at)} · <span class="subtle">${latest.stamp}</span></div>
        <div class="pub">${pub}</div>
        ${(latest.halts&&latest.halts.length)?`<ul class="halts">${latest.halts.map(h=>`<li>${esc(h)}</li>`).join("")}</ul>`:""}
      </div>
    </div>
    <div class="tiles">
      ${tile("Applicable", fmt(latest.total_applicable), dAppl!=null?`<span class="${dAppl>=0?'up':'down'}">${signed(dAppl)} vs baseline</span>`:"")}
      ${tile("Movement", (latest.movement_pct!=null?latest.movement_pct.toFixed(2):"–")+"%", latest.worst_employer?`worst ${esc(latest.worst_employer)} ${(latest.worst_employer_pct||0).toFixed(1)}%`:"")}
      ${tile("Live jobs", fmt(latest.live_jobs), latest.expired_jobs!=null?`${fmt(latest.expired_jobs)} expired (410)`:"")}
      ${tile("Baked", bake, "")}
    </div>
    <section class="block">
      <h2>Applicable set over the last ${byTime.length} run${byTime.length>1?"s":""}</h2>
      <div class="chartwrap" id="cw"><div class="tip" id="tip"></div></div>
      <div class="legend">
        <span><span class="dot g-good"></span>OK</span>
        <span><span class="dot g-warning"></span>Partial</span>
        <span><span class="dot g-critical"></span>Failed</span>
        <span class="subtle">line = applicable count · dot = run status</span>
      </div>
    </section>
    <section class="block">
      <h2>Run history</h2>
      <div class="card" style="padding:4px 6px">
        <table><thead><tr>
          <th>When</th><th>Status</th><th class="num">Applicable</th><th class="num">Movement</th><th>Publish</th><th>Halts</th>
        </tr></thead><tbody id="rows"></tbody></table>
      </div>
    </section>`;
  buildRows();
  draw();
}

function tile(k,v,d){ return `<div class="tile"><div class="k">${k}</div><div class="v num">${v}</div><div class="d">${d||"&nbsp;"}</div></div>`; }
function esc(s){ return String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }

function buildRows(){
  const tb=document.getElementById("rows");
  const desc=[...RUNS].sort((a,b)=>(b.ran_at||"").localeCompare(a.ran_at||""));
  desc.forEach((r,i)=>{
    const sev=SEV[r.severity]||SEV.warning;
    const tr=document.createElement("tr"); tr.className="run";
    const halts=(r.halts&&r.halts.length)?`<span class="down">${r.halts.length}</span>`:"<span class='subtle'>none</span>";
    const pub=r.published?`<a href="${r.deploy_url||"#"}" target="_blank" rel="noopener">deploy ↗</a>`:`<span class="subtle">${r.publish_status||"–"}</span>`;
    tr.innerHTML=`<td>${when(r.ran_at)}<div class="subtle">${ago(r.ran_at)}</div></td>
      <td><span class="pill b-${sev.cls}"><span class="dot g-${sev.cls}"></span>${r.status}</span></td>
      <td class="num">${fmt(r.total_applicable)}${r.applicable_delta!=null?` <span class="subtle">(${signed(r.applicable_delta)})</span>`:""}</td>
      <td class="num">${r.movement_pct!=null?r.movement_pct.toFixed(2)+"%":"–"}</td>
      <td>${pub}</td><td>${halts}</td>`;
    const det=document.createElement("tr"); det.className="detail"; det.style.display="none";
    det.innerHTML=`<td colspan="6">${detailHtml(r)}</td>`;
    tr.onclick=()=>{ det.style.display=det.style.display==="none"?"table-row":"none"; };
    tb.appendChild(tr); tb.appendChild(det);
  });
}

function detailHtml(r){
  let h="";
  if(r.tenants&&r.tenants.length){
    h+=`<table><thead><tr><th>Tenant</th><th>Platform</th><th>Modes</th><th class="num">Recs</th><th class="num">Δ</th><th class="num">Appl</th><th class="num">Density</th><th>Flag</th></tr></thead><tbody>`;
    for(const t of r.tenants){
      h+=`<tr><td>${esc(t.tenant)}</td><td class="subtle">${esc(t.platform)}</td><td class="subtle num">${esc(t.modes||"")}</td>
        <td class="num">${fmt(t.records)}</td><td class="num">${t.d_records!=null?signed(t.d_records):"–"}</td>
        <td class="num">${fmt(t.applicable)}</td><td class="num">${t.density!=null?t.density.toFixed(1)+"%":"–"}</td>
        <td class="flag-${(t.flag||'').split(':')[0]}">${esc(t.flag||"")}</td></tr>`;
    }
    h+=`</tbody></table>`;
  }
  if(r.halts&&r.halts.length){ h+=`<ul class="halts">${r.halts.map(x=>`<li>${esc(x)}</li>`).join("")}</ul>`; }
  h+=`<div class="subtle" style="padding:6px 2px 2px">git ${esc(r.git_head||"–")} · bake ${r.bake_job_pages!=null?fmt(r.bake_job_pages)+" pages / "+fmt(r.bake_listing_views)+" views":"–"} · ${esc(r.stamp)}</div>`;
  return h;
}

// ---- trend chart (single blue series; status-colored dots; crosshair + tooltip) ----
function cssv(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function draw(){
  const cw=document.getElementById("cw"); if(!cw) return;
  const old=cw.querySelector("svg"); if(old) old.remove();
  const data=[...RUNS].sort((a,b)=>(a.ran_at||"").localeCompare(b.ran_at||""))
                      .filter(r=>r.total_applicable!=null);
  if(!data.length) return;
  const W=1000,H=200,m={t:14,r:14,b:24,l:44};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const ys=data.map(d=>d.total_applicable);
  let lo=Math.min(...ys),hi=Math.max(...ys); if(lo===hi){lo-=1;hi+=1;}
  const pad=(hi-lo)*0.12; lo=Math.max(0,lo-pad); hi=hi+pad;
  const X=i=>m.l+(data.length===1?iw/2:iw*i/(data.length-1));
  const Y=v=>m.t+ih-ih*(v-lo)/(hi-lo);
  const NS="http://www.w3.org/2000/svg";
  const svg=document.createElementNS(NS,"svg"); svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
  svg.setAttribute("role","img"); svg.setAttribute("preserveAspectRatio","none");
  const mk=(n,a)=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);return e;};
  // gridlines + y ticks
  for(let g=0;g<=3;g++){ const v=lo+(hi-lo)*g/3, y=Y(v);
    svg.appendChild(mk("line",{x1:m.l,x2:W-m.r,y1:y,y2:y,stroke:cssv("--grid"),"stroke-width":1}));
    const tx=mk("text",{x:m.l-8,y:y+4,"text-anchor":"end","font-size":11,fill:cssv("--muted")});
    tx.textContent=Math.round(v).toLocaleString(); svg.appendChild(tx);
  }
  // line
  const dpath=data.map((d,i)=>`${i?"L":"M"}${X(i).toFixed(1)} ${Y(d.total_applicable).toFixed(1)}`).join(" ");
  svg.appendChild(mk("path",{d:dpath,fill:"none",stroke:cssv("--series"),"stroke-width":2,
    "stroke-linejoin":"round","stroke-linecap":"round"}));
  // status dots (2px surface ring so overlaps stay legible)
  const sc={good:cssv("--good"),warning:cssv("--warning"),critical:cssv("--critical")};
  data.forEach((d,i)=>{ svg.appendChild(mk("circle",{cx:X(i),cy:Y(d.total_applicable),r:4.5,
    fill:sc[d.severity]||sc.warning,stroke:cssv("--surface"),"stroke-width":2})); });
  // crosshair + hover targets
  const cross=mk("line",{x1:0,x2:0,y1:m.t,y2:m.t+ih,stroke:cssv("--axis"),"stroke-width":1,opacity:0});
  svg.appendChild(cross);
  const tip=document.getElementById("tip");
  data.forEach((d,i)=>{ const hit=mk("rect",{x:X(i)-14,y:m.t,width:28,height:ih,fill:"transparent"});
    hit.style.cursor="pointer";
    hit.onmouseenter=()=>{ cross.setAttribute("x1",X(i)); cross.setAttribute("x2",X(i)); cross.setAttribute("opacity",1);
      const sev=SEV[d.severity]||SEV.warning;
      tip.innerHTML=`<b>${fmt(d.total_applicable)}</b> applicable · ${sev.label}<br><span class="subtle">${when(d.ran_at)}</span>`;
      const px=X(i)/W*cw.clientWidth, py=Y(d.total_applicable)/H*cw.clientHeight;
      tip.style.opacity=1; tip.style.left=Math.min(cw.clientWidth-150,Math.max(6,px+10))+"px"; tip.style.top=Math.max(4,py-46)+"px";
    };
    hit.onmouseleave=()=>{ cross.setAttribute("opacity",0); tip.style.opacity=0; };
    svg.appendChild(hit);
  });
  cw.appendChild(svg);
}
window.addEventListener("resize",draw);
</script>
</body>
</html>
"""
