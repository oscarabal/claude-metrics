"""HTML pages for the sessions of Claude Code: a list and the detail of one session. They only render."""
import html

PALETTE = {"input": "#5794F2", "cache_read": "#8AB8FF", "cache_write": "#2EC4B6", "output": "#F2994A"}
LABELS = {"input": "Entrada", "cache_read": "Caché leída", "cache_write": "Caché escrita", "output": "Salida"}

CSS = """
:root{--bg:#f6f6f3;--surface:#fff;--fg:#1d2127;--muted:#5d6672;--line:#dcdcd5;--free:#e4e4de;--accent:#5794F2}
@media (prefers-color-scheme:dark){:root{--bg:#14171b;--surface:#1c2025;--fg:#e8eaec;--muted:#9aa3ad;--line:#2d333a;--free:#2b3037}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif;padding:24px max(16px,env(safe-area-inset-left))}
.wrap{max-width:1000px;margin:0 auto}
a{color:var(--accent)}
h1{font-size:24px;margin:4px 0 6px;overflow-wrap:anywhere}
h2{font-size:15px;margin:28px 0 10px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.sub{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px}
.kpi b{display:block;font-size:22px}
.kpi span{color:var(--muted);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.ctxhead{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.bar{display:flex;height:16px;border-radius:4px;overflow:hidden;background:var(--free)}
.bar i{display:block;height:100%}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:13px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--muted);font-weight:600;font-size:13px}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
svg{width:100%;height:auto;display:block}
svg text{fill:var(--muted);font-size:11px}
.note{color:var(--muted);font-size:13px;margin-top:28px}
.tools{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:14px 0}
input[type=search]{padding:7px 10px;border:1px solid var(--line);border-radius:5px;background:var(--surface);color:var(--fg);min-width:240px;font:inherit}
th.s{cursor:pointer;user-select:none}
th.s:hover{color:var(--fg)}
td a{overflow-wrap:anywhere}
.tag{font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:1px 7px;margin-left:6px}
"""

LIST_JS = """
var q=document.getElementById('q'),tb=document.querySelector('tbody'),rows=[].slice.call(tb.rows),cnt=document.getElementById('cnt');
function filt(){var v=q.value.toLowerCase(),n=0;rows.forEach(function(r){var ok=r.textContent.toLowerCase().indexOf(v)>=0;r.style.display=ok?'':'none';if(ok)n++});cnt.textContent=n}
q.addEventListener('input',filt);
document.querySelectorAll('th.s').forEach(function(th,i){var asc=false;th.addEventListener('click',function(){asc=!asc;
 rows.sort(function(a,b){var x=a.cells[i].dataset.v||a.cells[i].textContent,y=b.cells[i].dataset.v||b.cells[i].textContent,nx=parseFloat(x),ny=parseFloat(y);
  var c=(!isNaN(nx)&&!isNaN(ny))?nx-ny:String(x).localeCompare(String(y));return asc?c:-c});
 rows.forEach(function(r){tb.appendChild(r)})})});
document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleString()});
"""

TIME_JS = "document.querySelectorAll('time[data-ms]').forEach(function(t){t.textContent=new Date(+t.dataset.ms).toLocaleString()})"


def e(v):
    return html.escape(str(v), quote=True)


def kilo(n):
    n = float(n)
    if n >= 1_000_000:
        return ("%.2f" % (n / 1_000_000)).rstrip("0").rstrip(".") + "M"
    if n >= 1000:
        return "%.1fk" % (n / 1000)
    return "%d" % n


def usd(v):
    return "$%.2f" % v if v >= 0.01 or v == 0 else "$%.3f" % v


def when(ms):
    return '<time data-ms="%d"></time>' % ms if ms else "—"


def duration(ms):
    s = int(ms / 1000)
    if s < 60:
        return "%d s" % s
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 86400:
        return "%d h %d min" % (s // 3600, (s % 3600) // 60)
    return "%d d %d h" % (s // 86400, (s % 86400) // 3600)


def context_card(d):
    last = d["last"]
    if not last:
        return '<div class="card sub">Esta sesión no tiene mensajes del asistente con tokens.</div>'
    parts = {k: last[k] for k in ("input", "cache_read", "cache_write", "output")}
    used = sum(parts.values())
    limit = d["limit"]
    pct = used / limit * 100
    head = '<b>%.0f %% usado</b><span class="sub">%s / %s · quedan %s</span>' % (min(pct, 100), kilo(used), kilo(limit), kilo(max(limit - used, 0)))
    scale = max(limit, used)
    segs = "".join('<i style="width:%.2f%%;background:%s" title="%s: %s"></i>' % (v / scale * 100, PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items() if v)
    legend = "".join('<span><i style="background:%s"></i>%s %s</span>' % (PALETTE[k], LABELS[k], kilo(v)) for k, v in parts.items())
    return ('<div class="card"><div class="ctxhead">%s</div><div class="bar">%s</div><div class="legend">%s'
            '<span><i style="background:var(--free)"></i>Libre</span></div>'
            '<div class="sub" style="margin-top:8px;font-size:13px">Modelo: %s. Contexto del último mensaje del hilo principal. %s</div></div>'
            % (head, segs, legend, e(last["model"]), e(d["limit_note"])))


def line_chart(points, title, fmt, color, marks=(), note_marks=""):
    if len(points) < 2:
        return '<div class="card sub">%s: hacen falta al menos dos puntos.</div>' % e(title)
    w, h, left, right, top, bottom = 760, 200, 56, 12, 14, 26
    top_value = max(points) * 1.1 or 1
    n = len(points)

    def x(i):
        return left + (w - left - right) * i / (n - 1)

    def y(v):
        return top + (h - top - bottom) * (1 - v / top_value)

    grid = ""
    for k in range(5):
        v = top_value * k / 4
        grid += '<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="currentColor" opacity=".12"/><text x="%d" y="%.1f" text-anchor="end">%s</text>' % (
            left, w - right, y(v), y(v), left - 6, y(v) + 4, fmt(v))
    path = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", x(i), y(v)) for i, v in enumerate(points))
    marked = "".join('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="#E0B400" stroke-dasharray="3 3"/>' % (x(i), x(i), top, h - bottom) for i in marks if 0 <= i < n)
    axis = '<text x="%d" y="%d">mensaje 1</text><text x="%d" y="%d" text-anchor="end">mensaje %d</text>' % (left, h - 8, w - right, h - 8, n)
    note = (" · " + note_marks) if marks else ""
    return ('<div class="card"><div class="sub" style="font-size:13px;margin-bottom:6px">%s%s</div><svg viewBox="0 0 %d %d" role="img" aria-label="%s">%s%s'
            '<path d="%s" fill="none" stroke="%s" stroke-width="2"/>%s</svg></div>'
            % (e(title), e(note), w, h, e(title), grid, marked, path, color, axis))


def table(headers, rows, numeric=()):
    if not rows:
        return '<div class="card sub">Sin datos.</div>'
    head = "".join('<th class="%s">%s</th>' % ("n" if i in numeric else "", e(hd)) for i, hd in enumerate(headers))
    body = "".join("<tr>%s</tr>" % "".join('<td class="%s">%s</td>' % ("n" if i in numeric else "", c) for i, c in enumerate(r)) for r in rows)
    return '<div class="card scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)


def render_detail(d, dashboard_url):
    main = d["main"]
    ctx = [sum(m["tokens"].values()) for m in main]
    times = [m["t"] for m in main]
    marks = [sum(1 for t in times if t <= c[0]) for c in d["compactions"]]
    known = [m for m in main if m["cost"] is not None]
    cum, running = [], 0.0
    for m in main:
        running += m["cost"] or 0
        cum.append(running)
    cost_total = d["cost_known"]
    coverage = "%d de %d mensajes con coste" % (d["msgs_known"], d["msgs_total"])

    model_rows = [[e(m), str(v[0]), kilo(v[1]), usd(v[2]) if v[3] else "—"] for m, v in sorted(d["models"].items(), key=lambda kv: -kv[1][1])]
    tool_rows = [[e(n), str(v[0]), str(v[1])] for n, v in sorted(d["tools"].items(), key=lambda kv: -kv[1][0])]
    skill_rows = [[e(n), str(v[0]), str(v[1]), usd(d["attributed"][n]) if n in d["attributed"] else "—"]
                  for n, v in sorted(d["skills"].items(), key=lambda kv: -(kv[1][0] + kv[1][1]))]
    comp_rows = [[when(t), e(trigger or "—"), kilo(pre), kilo(post)] for t, pre, post, trigger in d["compactions"]]
    sub = d["sub"]
    sub_rows = [[str(sub["agents"]), str(sub["messages"]), kilo(sub["tokens"]), usd(sub["cost"]) if sub["cost"] else "—"]] if sub["agents"] else []

    span = (d["updated"] - d["created"]) if d["updated"] and d["created"] else 0
    meta = " · ".join(x for x in (e(d["project"]), e(d["branch"]) if d["branch"] else "", "%d mensajes del hilo principal" % len(main), "duración %s" % duration(span)) if x)
    parts = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>%s · Sesión de Claude Code</title><style>%s</style></head><body><div class='wrap'>" % (e(d["title"] or d["id"]), CSS),
        "<div class='sub'><a href='%s'>← Dashboard</a> · <a href='/sessions'>Todas las sesiones</a></div>" % e(dashboard_url),
        "<h1>%s</h1><div class='sub'>%s</div>" % (e(d["title"] or d["id"]), meta),
        "<div class='sub'>Creada %s · actualizada %s</div>" % (when(d["created"]), when(d["updated"])),
        "<div class='kpis'>",
        "<div class='kpi'><b>%s</b><span>Coste conocido (%s)</span></div>" % (usd(cost_total) if d["msgs_known"] else "—", e(coverage)),
        "<div class='kpi'><b>%s</b><span>Tokens (con subagentes)</span></div>" % kilo(d["tokens_total"]),
        "<div class='kpi'><b>%d</b><span>Herramientas llamadas</span></div>" % sum(v[0] for v in d["tools"].values()),
        "<div class='kpi'><b>%d</b><span>Compactaciones</span></div>" % len(d["compactions"]),
        "<div class='kpi'><b>%d</b><span>Subagentes</span></div>" % sub["agents"],
        "</div>",
        "<h2>Contexto</h2>", context_card(d),
        "<h2>Evolución</h2>",
        line_chart(ctx, "Tamaño del contexto en cada mensaje del hilo principal (tokens)", kilo, PALETTE["input"], marks, "las líneas amarillas son compactaciones"),
    ]
    if len(known) >= 2:
        parts += ["<div style='height:12px'></div>", line_chart(cum, "Coste conocido acumulado (USD)", usd, PALETTE["output"])]
    parts += ["<h2>Modelos</h2>", table(["Modelo", "Mensajes", "Tokens", "Coste conocido"], model_rows, numeric=(1, 2, 3)),
              "<h2>Skills y comandos</h2>", table(["Nombre", "Como comando", "Como skill", "Coste atribuido"], skill_rows, numeric=(1, 2, 3)),
              "<h2>Herramientas</h2>", table(["Herramienta", "Llamadas", "Errores"], tool_rows, numeric=(1, 2))]
    if comp_rows:
        parts += ["<h2>Compactaciones</h2>", table(["Cuándo", "Disparo", "Tokens antes", "Tokens después"], comp_rows, numeric=(2, 3))]
    if sub_rows:
        parts += ["<h2>Subagentes</h2>", table(["Subagentes", "Mensajes", "Tokens", "Coste conocido"], sub_rows, numeric=(0, 1, 2, 3))]
    parts += [
        "<p class='note'>Datos de los ficheros de conversación de Claude Code, leídos en solo lectura. Aquí no aparece el texto de la conversación. "
        "El coste sale de la telemetría y solo existe para las llamadas registradas desde que se activó; el resto muestra «—». "
        "El título lo pone Claude Code a partir de la conversación.</p>",
        "<script>%s</script></div></body></html>" % TIME_JS,
    ]
    return "".join(parts)


def render_list(rows, dashboard_url, note, toggle_href=None):
    """rows: (id, title, project, model, messages, tokens, cost or None, created, updated, subagents)"""
    def cell(v, text):
        return '<td class="n" data-v="%s">%s</td>' % (e(v), text)

    body = []
    for sid, title, project, model, msgs, tokens, cost, created, updated, subs in rows:
        tag = '<span class="tag">%d subagentes</span>' % subs if subs else ""
        body.append('<tr><td><a href="/session/%s">%s</a>%s</td><td>%s</td><td>%s</td>%s%s%s%s%s</tr>' % (
            e(sid), e(title or sid[:8]), tag, e(project), e(model), cell(msgs, str(msgs)), cell(tokens, kilo(tokens)),
            cell(cost if cost is not None else -1, usd(cost) if cost is not None else "—"), cell(created, when(created)), cell(updated, when(updated))))
    heads = ["Sesión", "Proyecto", "Modelo", "Mensajes", "Tokens", "Coste conocido", "Creada", "Actualizada"]
    th = "".join('<th class="s%s">%s</th>' % (" n" if i >= 3 else "", h) for i, h in enumerate(heads))
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Sesiones de Claude Code</title><style>%s</style></head><body><div class='wrap'>"
            "<div class='sub'><a href='%s'>← Dashboard</a></div><h1>Sesiones</h1><div class='sub'>%s</div>"
            "<div class='tools'><input id='q' type='search' placeholder='Filtrar por título, proyecto o modelo' aria-label='Filtrar'>"
            "<span class='sub'><b id='cnt'>%d</b> de %d sesiones</span></div>"
            "<div class='card scroll'><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>"
            "<p class='note'>Pulsa una cabecera para ordenar. El coste sale de la telemetría y solo existe desde que se activó; «—» es una sesión sin coste conocido. "
            "Aquí no aparece el texto de la conversación.</p><script>%s</script></div></body></html>"
            % (CSS, e(dashboard_url), e(note), len(rows), len(rows), th, "".join(body), LIST_JS))


def not_found(dashboard_url):
    return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>Sesión no encontrada</title><style>%s</style>"
            "<body><div class='wrap'><h1>Sesión no encontrada</h1><p class='sub'>Claude Code no tiene una sesión con ese identificador.</p>"
            "<a href='%s'>← Dashboard</a></div></body></html>" % (CSS, e(dashboard_url)))
