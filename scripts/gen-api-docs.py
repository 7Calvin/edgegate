#!/usr/bin/env python3
"""Generate a self-contained, sectioned, searchable API reference HTML from an OpenAPI 3.1 spec."""
import json, sys, html, re

spec = json.load(open(sys.argv[1], encoding="utf-8"))
OUT = sys.argv[2]

info = spec.get("info", {})
paths = spec.get("paths", {})
schemas = spec.get("components", {}).get("schemas", {})

# ---- section order (monitoring/common first, then resources) ----
ORDER = ["Authentication", "Health", "System / Update", "Users", "Admin",
         "Connections", "VPN", "IPsec", "Firewall", "Reverse Proxy",
         "ACME DNS-01", "Root"]
METHOD_ORDER = {"get": 0, "post": 1, "put": 2, "patch": 3, "delete": 4}

# Monitoring subset (read-only status/health/metrics) for the "Monitoramento" tab:
# OpenVPN service + clients, IPsec tunnels, server + version status, users, connection
# stats, firewall/proxy status, liveness.
_MON_EXACT = {
    "/health", "/ready",
    "/api/v1/system/info", "/api/v1/system/version", "/api/v1/admin/system/health",
    "/api/v1/vpn/server/status", "/api/v1/vpn/server/connections",
    "/api/v1/ipsec/statusall", "/api/v1/ipsec/logs", "/api/v1/ipsec/connections",
    "/api/v1/firewall/status", "/api/v1/proxy/status",
    "/api/v1/users", "/api/v1/users/stats/summary",
    "/api/v1/connections", "/api/v1/connections/active", "/api/v1/connections/live",
    "/api/v1/connections/stats/summary", "/api/v1/connections/stats/bandwidth",
    "/api/v1/connections/throughput",
}

def is_mon(method, path):
    """True if this GET endpoint belongs in the monitoring view."""
    if method != "get":
        return False
    return path in _MON_EXACT or path.startswith("/api/v1/ipsec/status")

def esc(s): return html.escape(str(s) if s is not None else "")

def resolve(node, _seen=None):
    """Resolve a $ref one level."""
    if isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"].split("/")[-1]
        return schemas.get(ref, {})
    return node

def example(schema, depth=0):
    """Build a minimal example value from a JSON schema."""
    if schema is None or depth > 5:
        return None
    schema = resolve(schema)
    if not isinstance(schema, dict):
        return None
    if "example" in schema: return schema["example"]
    if "default" in schema: return schema["default"]
    if "enum" in schema and schema["enum"]: return schema["enum"][0]
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema and schema[key]:
            return example(schema[key][0], depth + 1)
    t = schema.get("type")
    if isinstance(t, list): t = next((x for x in t if x != "null"), t[0])
    if t == "object" or "properties" in schema:
        out = {}
        for k, v in (schema.get("properties") or {}).items():
            out[k] = example(v, depth + 1)
        return out
    if t == "array":
        return [example(schema.get("items", {}), depth + 1)]
    if t == "string":
        fmt = schema.get("format", "")
        return {"date-time": "2026-08-24T20:26:47Z", "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "email": "user@example.com", "password": "••••••••"}.get(fmt, "string")
    if t == "integer": return 0
    if t == "number": return 0.0
    if t == "boolean": return True
    return None

def body_schema_name(op):
    rb = op.get("requestBody", {})
    content = rb.get("content", {})
    js = content.get("application/json", {})
    sc = js.get("schema", {})
    if "$ref" in sc: return sc["$ref"].split("/")[-1]
    return None

def json_block(value):
    try:
        txt = json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        txt = str(value)
    return f'<pre class="code"><code>{esc(txt)}</code></pre>'

def slug(method, path):
    return "op-" + method + re.sub(r"[^a-zA-Z0-9]+", "-", path).strip("-")

# ---- collect operations grouped by tag ----
groups = {}
for path, ops in paths.items():
    for method, op in ops.items():
        if method not in METHOD_ORDER: continue
        tag = (op.get("tags") or ["Other"])[0]
        groups.setdefault(tag, []).append((path, method, op))

for tag in groups:
    groups[tag].sort(key=lambda x: (x[0], METHOD_ORDER[x[1]]))

ordered_tags = [t for t in ORDER if t in groups] + [t for t in groups if t not in ORDER]

total_ops = sum(len(v) for v in groups.values())
mon_count = sum(1 for ops in groups.values() for path, method, op in ops if is_mon(method, path))

# ---- render sidebar ----
nav = []
for tag in ordered_tags:
    ops = groups[tag]
    nav.append(f'<div class="nav-group" data-group="{esc(tag)}">')
    nav.append(f'<div class="nav-title">{esc(tag)}<span class="badge">{len(ops)}</span></div>')
    for path, method, op in ops:
        sid = slug(method, path)
        mon = ' data-mon="1"' if is_mon(method, path) else ''
        nav.append(
            f'<a class="nav-link" href="#{sid}" data-search="{esc((method+" "+path+" "+op.get("summary","")).lower())}"{mon}>'
            f'<span class="m m-{method}">{method.upper()}</span>'
            f'<span class="np">{esc(path)}</span></a>')
    nav.append('</div>')

# ---- render content ----
content = []
for tag in ordered_tags:
    content.append(f'<section class="tag-section" id="tag-{esc(re.sub(r"[^a-zA-Z0-9]+","-",tag))}" data-group="{esc(tag)}">')
    content.append(f'<h2 class="tag-h">{esc(tag)}</h2>')
    for path, method, op in groups[tag]:
        sid = slug(method, path)
        summary = op.get("summary") or ""
        desc = op.get("description") or ""
        secured = bool(op.get("security"))
        admin = "admin" in (summary + " " + desc).lower()
        search_txt = esc((method + " " + path + " " + summary + " " + desc).lower())
        mon = ' data-mon="1"' if is_mon(method, path) else ''
        content.append(f'<article class="op" id="{sid}" data-search="{search_txt}"{mon}>')
        content.append('<div class="op-head">'
                       f'<span class="m m-{method}">{method.upper()}</span>'
                       f'<code class="op-path">{esc(path)}</code>')
        if admin:
            content.append('<span class="tag-pill pill-admin">admin</span>')
        elif secured:
            content.append('<span class="tag-pill pill-auth">auth</span>')
        else:
            content.append('<span class="tag-pill pill-open">público</span>')
        content.append('</div>')
        if summary: content.append(f'<p class="op-summary">{esc(summary)}</p>')
        if desc and desc != summary:
            content.append(f'<p class="op-desc">{esc(desc)}</p>')

        # parameters
        params = op.get("parameters", [])
        if params:
            rows = []
            for p in params:
                psc = p.get("schema", {})
                pt = psc.get("type", "")
                if "$ref" in psc: pt = psc["$ref"].split("/")[-1]
                req = ' <span class="req-star">*</span>' if p.get("required") else ""
                rows.append(f'<tr><td><code>{esc(p.get("name"))}</code>{req}</td>'
                            f'<td class="muted">{esc(p.get("in"))}</td>'
                            f'<td class="muted">{esc(pt)}</td>'
                            f'<td>{esc(p.get("description",""))}</td></tr>')
            content.append('<div class="sub">Parâmetros</div>'
                           '<div class="tbl-wrap"><table class="tbl"><thead><tr>'
                           '<th>Nome</th><th>Em</th><th>Tipo</th><th>Descrição</th></tr></thead>'
                           f'<tbody>{"".join(rows)}</tbody></table></div>')

        # request body
        bname = body_schema_name(op)
        if bname and bname in schemas:
            ex = example({"$ref": f"#/components/schemas/{bname}"})
            content.append(f'<div class="sub">Request body <span class="muted">({esc(bname)})</span></div>')
            content.append(json_block(ex))

        # responses (show first 2xx with a body)
        resp = op.get("responses", {})
        shown = False
        for code in sorted(resp.keys()):
            if not code.startswith("2"): continue
            r = resp[code]
            js = r.get("content", {}).get("application/json", {})
            sc = js.get("schema")
            if sc is not None:
                ex = example(sc)
                content.append(f'<div class="sub">Resposta <span class="ok">{esc(code)}</span> '
                               f'<span class="muted">{esc(r.get("description",""))}</span></div>')
                content.append(json_block(ex))
                shown = True
                break
        if not shown:
            codes = ", ".join(sorted(resp.keys()))
            if codes:
                content.append(f'<div class="sub">Respostas <span class="muted">{esc(codes)}</span></div>')
        content.append('</article>')
    content.append('</section>')

HTML = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EdgeGate API — Referência v{esc(info.get('version',''))}</title>
<style>
/* EdgeGate design tokens (dark-only, matches the panel index.css) */
:root{{
  --bg:#06090f; --panel:#0d1420; --ink:#dbe7f0; --muted:#5f7387; --line:#16283a;
  --brand:#22d3ee; --code-bg:#0a0f18; --code-ink:#dbe7f0; --badge-ink:#06090f;
  --get:#a3e635; --post:#22d3ee; --put:#f5c451; --patch:#f5c451; --delete:#ff6b6b;
  --pill-admin-bg:rgba(255,107,107,.14); --pill-admin-ink:#ff6b6b;
  --pill-auth-bg:rgba(34,211,238,.14); --pill-auth-ink:#22d3ee;
  --pill-open-bg:rgba(163,230,53,.14); --pill-open-ink:#a3e635;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.6 'IBM Plex Sans',system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}}
code,pre,.np,.op-path{{font-family:'IBM Plex Mono',ui-monospace,"Cascadia Code",Menlo,Consolas,monospace;}}
.hero{{padding:32px 28px 22px;border-bottom:1px solid var(--line);background:var(--panel);}}
.hero h1{{margin:0;font-size:26px;letter-spacing:-.02em;}}
.hero .ver{{font-size:14px;font-weight:600;color:var(--badge-ink);background:var(--brand);
  padding:2px 9px;border-radius:999px;vertical-align:middle;margin-left:8px;}}
.hero p{{margin:8px 0 0;color:var(--muted);max-width:70ch;}}
.hero .meta{{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px;}}
.chip{{font-size:12.5px;background:var(--bg);border:1px solid var(--line);
  padding:4px 10px;border-radius:8px;color:var(--muted);}}
.chip b{{color:var(--ink);font-weight:600;}}
.authbox{{margin:20px 28px;background:var(--panel);border:1px solid var(--line);
  border-radius:12px;padding:18px 20px;}}
.authbox h3{{margin:0 0 8px;font-size:15px;}}
.authbox p{{margin:6px 0;color:var(--muted);font-size:14px;}}
.authbox code{{background:var(--bg);border:1px solid var(--line);padding:1px 6px;border-radius:6px;
  font-size:13px;color:var(--ink);}}
.authbox .code{{margin-top:10px;}}
.tabs{{display:flex;gap:8px;padding:16px 28px 0;flex-wrap:wrap;}}
.tab{{background:var(--panel);border:1px solid var(--line);color:var(--muted);font:inherit;
  font-size:13.5px;font-weight:600;padding:8px 15px;border-radius:9px;cursor:pointer;}}
.tab:hover{{color:var(--ink);border-color:var(--brand);}}
.tab.active{{background:var(--brand);color:var(--badge-ink);border-color:var(--brand);}}
.tab .tcount{{opacity:.75;font-weight:700;margin-left:3px;}}
.layout{{display:grid;grid-template-columns:300px 1fr;align-items:start;gap:0;}}
.sidebar{{position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid var(--line);
  background:var(--panel);padding:16px 12px;}}
#search{{width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:9px;
  background:var(--bg);color:var(--ink);font-size:14px;margin-bottom:12px;}}
#search:focus{{outline:2px solid var(--brand);outline-offset:1px;border-color:var(--brand);}}
.nav-group{{margin-bottom:14px;}}
.nav-title{{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);padding:4px 8px;display:flex;justify-content:space-between;align-items:center;}}
.nav-title .badge{{background:var(--bg);border:1px solid var(--line);border-radius:999px;
  padding:0 7px;font-size:11px;font-weight:600;}}
.nav-link{{display:flex;align-items:center;gap:7px;padding:4px 8px;border-radius:7px;
  text-decoration:none;color:var(--ink);font-size:12.5px;}}
.nav-link:hover{{background:var(--bg);}}
.nav-link .np{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted);}}
.content{{padding:8px 28px 80px;min-width:0;}}
.tag-h{{font-size:20px;margin:34px 0 4px;padding-bottom:8px;border-bottom:2px solid var(--line);letter-spacing:-.01em;}}
.op{{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;margin:16px 0;}}
.op-head{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}}
.op-path{{font-size:14px;font-weight:600;word-break:break-all;}}
.m{{font-size:11px;font-weight:800;color:var(--badge-ink);padding:3px 8px;border-radius:6px;letter-spacing:.03em;flex:none;}}
.m-get{{background:var(--get)}}.m-post{{background:var(--post)}}.m-put{{background:var(--put)}}
.m-patch{{background:var(--patch)}}.m-delete{{background:var(--delete)}}
.tag-pill{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:auto;}}
.pill-admin{{background:var(--pill-admin-bg);color:var(--pill-admin-ink);}}
.pill-auth{{background:var(--pill-auth-bg);color:var(--pill-auth-ink);}}
.pill-open{{background:var(--pill-open-bg);color:var(--pill-open-ink);}}
.op-summary{{margin:10px 0 2px;font-weight:600;}}
.op-desc{{margin:4px 0;color:var(--muted);font-size:13.5px;white-space:pre-line;}}
.sub{{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);margin:14px 0 6px;}}
.ok{{color:var(--get);font-weight:700;}}
.muted{{color:var(--muted);font-weight:400;}}
.tbl-wrap{{overflow-x:auto;}}
.tbl{{width:100%;border-collapse:collapse;font-size:13px;}}
.tbl th{{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
  color:var(--muted);padding:6px 10px;border-bottom:1px solid var(--line);}}
.tbl td{{padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;}}
.tbl code{{font-size:12.5px;}}
.req-star{{color:var(--delete);font-weight:800;}}
.code{{background:var(--code-bg);color:var(--code-ink);border-radius:9px;padding:12px 14px;
  overflow-x:auto;font-size:12.5px;line-height:1.55;margin:0;}}
.code code{{color:inherit;background:none;padding:0;}}
.empty{{padding:40px;text-align:center;color:var(--muted);}}
@media (max-width:820px){{
  .layout{{grid-template-columns:1fr;}}
  .sidebar{{position:static;height:auto;max-height:none;border-right:none;border-bottom:1px solid var(--line);}}
}}
</style>
</head>
<body>

<header class="hero">
  <h1>EdgeGate API <span class="ver">v{esc(info.get('version',''))}</span></h1>
  <p>Referência completa da API REST — todos os endpoints em seções, com busca. Use a barra lateral ou o campo de busca para filtrar por caminho, método ou descrição.</p>
  <div class="meta">
    <span class="chip">OpenAPI <b>3.1</b></span>
    <span class="chip"><b>{total_ops}</b> endpoints</span>
    <span class="chip"><b>{len(ordered_tags)}</b> seções</span>
    <span class="chip">Base URL <b>https://&lt;host&gt;/api/v1</b></span>
  </div>
</header>

<div class="authbox">
  <h3>🔐 Autenticação</h3>
  <p>Toda chamada autenticada usa <code>Authorization: Bearer &lt;token&gt;</code>. O token pode ser um <b>JWT</b> (obtido no login) ou uma <b>API key</b> de um usuário de serviço (<code>user_type = SERVICE</code>).</p>
  <p><b>Trusted Host:</b> o IP de origem é validado em <b>toda</b> requisição autenticada — um IP fora da allowlist do usuário recebe <code>403</code>, mesmo com token válido.</p>
  <p>As pílulas em cada endpoint indicam o nível: <span class="tag-pill pill-admin">admin</span> exige privilégio de administrador, <span class="tag-pill pill-auth">auth</span> qualquer usuário autenticado, <span class="tag-pill pill-open">público</span> sem token.</p>
  <div class="code"><code>curl -H "Authorization: Bearer &lt;API_KEY&gt;" https://&lt;host&gt;/api/v1/system/info</code></div>
</div>

<div class="tabs" id="tabs">
  <button class="tab active" data-view="all">Todos <span class="tcount">{total_ops}</span></button>
  <button class="tab" data-view="mon">📡 Monitoramento <span class="tcount">{mon_count}</span></button>
</div>

<div class="layout">
  <aside class="sidebar">
    <input id="search" type="search" placeholder="Buscar endpoint…" autocomplete="off">
    <nav id="nav">{''.join(nav)}</nav>
  </aside>
  <main class="content" id="content">
    {''.join(content)}
    <div class="empty" id="noresult" style="display:none">Nenhum endpoint encontrado.</div>
  </main>
</div>

<script>
(function(){{
  var q=document.getElementById('search');
  var ops=[].slice.call(document.querySelectorAll('.op'));
  var links=[].slice.call(document.querySelectorAll('.nav-link'));
  var sections=[].slice.call(document.querySelectorAll('.tag-section'));
  var navGroups=[].slice.call(document.querySelectorAll('.nav-group'));
  var noresult=document.getElementById('noresult');
  var monOnly=false;
  function apply(){{
    var t=q.value.trim().toLowerCase();
    var any=false;
    ops.forEach(function(o){{
      var hit=(!t||o.getAttribute('data-search').indexOf(t)>=0)&&(!monOnly||o.hasAttribute('data-mon'));
      o.style.display=hit?'':'none'; if(hit)any=true;
    }});
    links.forEach(function(l){{
      l.style.display=((!t||l.getAttribute('data-search').indexOf(t)>=0)&&(!monOnly||l.hasAttribute('data-mon')))?'':'none';
    }});
    sections.forEach(function(s){{
      var vis=s.querySelectorAll('.op:not([style*="none"])').length>0;
      s.style.display=vis?'':'none';
    }});
    navGroups.forEach(function(g){{
      var vis=g.querySelectorAll('.nav-link:not([style*="none"])').length>0;
      g.style.display=vis?'':'none';
    }});
    noresult.style.display=any?'none':'';
  }}
  q.addEventListener('input',apply);
  document.getElementById('tabs').addEventListener('click',function(e){{
    var b=e.target.closest('.tab'); if(!b)return;
    monOnly=b.getAttribute('data-view')==='mon';
    [].slice.call(document.querySelectorAll('.tab')).forEach(function(x){{x.classList.toggle('active',x===b);}});
    apply();
  }});
  // smooth scroll + keep hash
  document.getElementById('nav').addEventListener('click',function(e){{
    var a=e.target.closest('a'); if(!a)return;
    e.preventDefault();
    var el=document.querySelector(a.getAttribute('href'));
    if(el)el.scrollIntoView({{behavior:'smooth',block:'start'}});
  }});
}})();
</script>
</body>
</html>
"""

open(OUT, "w", encoding="utf-8").write(HTML)
print("wrote", OUT, len(HTML), "bytes;", total_ops, "ops")
