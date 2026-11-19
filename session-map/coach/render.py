"""Markdown rendering of the report, written to be pasted into an AI chat (same layout as the OpenCode module)."""
import json

AI_PROMPT = """Eres un revisor experto en el uso de agentes de programación (Claude Code). Este informe resume cómo los usa una persona: coste, modelos, effort, herramientas, errores, contexto, permisos, skills y comandos. No contiene el texto de las conversaciones.

Tu tarea:

1. Revisa los hallazgos de la sección 2, que salen de reglas automáticas: confirma, matiza o descarta cada uno con los datos de las demás secciones.
2. Busca en las tablas otras mejoras que las reglas no cubran. En particular, cruza el modelo fijado de cada comando (sección 7) con la salud de ese modelo (sección 4), el coste por effort y por origen (sección 6) con el tipo de trabajo, y el contexto inicial de las sesiones (sección 5) con lo que se carga en ellas.
3. Entrega una lista priorizada por impacto. Para cada mejora indica: qué cambiar exactamente (una regla lista para pegar en CLAUDE.md, una regla allow para settings.json, el modelo o effort por defecto, el modelo que fijar en un comando, una skill o comando que crear, dividir o retirar, un hábito al escribir prompts), por qué (cifras de este informe), el impacto esperado y cómo comprobar después que funcionó.

Reglas: usa solo las cifras del informe y no inventes otras; si la muestra es pequeña, dilo; si algo no se puede saber con estos datos, di qué dato faltaría. El coste es el que estima Claude Code a precio de API: con suscripción es un coste equivalente, no lo que se paga, y lo que limita es el uso de tokens."""

LABELS = {
    "cost_usd": "Coste equivalente (conocido)", "cost_coverage": "Mensajes con coste conocido", "tokens": "Tokens",
    "cache_hit": "Acierto de caché", "sessions": "Sesiones", "turns": "Turnos", "assistant_messages": "Mensajes del asistente",
    "tool_calls": "Llamadas a herramientas", "tool_errors": "Errores de herramientas", "tool_error_rate": "Tasa de error de herramientas",
    "compactions": "Compactaciones", "aborted": "Respuestas interrumpidas",
}
PCT = {"cache_hit", "tool_error_rate", "cost_share", "error_rate", "rate", "subagent_cost_share", "cost_coverage"}


def usd(v):
    return "—" if v is None else "%.2f $" % v if abs(v) >= 0.01 or v == 0 else "%.4f $" % v


def usd4(v):
    return "—" if v is None else "%.4f $" % v


def tok(v):
    return "%.1f M" % (v / 1e6) if v >= 1e6 else "%.0f k" % (v / 1e3) if v >= 1e3 else "%d" % v


def kb(v):
    return "%.0f kB" % (v / 1000) if v >= 1000 else "%d B" % v


def pct(v):
    return "%.1f %%" % (100 * v)


def fmt(key, v):
    if v is None:
        return "—"
    if key in PCT:
        return pct(v)
    if key.endswith("usd") or key.startswith("cost"):
        return usd(v)
    if key.startswith("tokens"):
        return tok(v)
    return str(v)


def _rate(a, b):
    return a / b if b else 0.0


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def render(r):
    s, prev, t = r["summary"], r["previous"], r["tables"]
    L = []
    add = L.append
    for line in ("---", "informe: mejoras de uso de agentes", "fuente: %s" % r["source"], "generado: %s" % r["generated"],
                 "periodo: %s (%s a %s, UTC)" % (r["period"]["label"], r["period"]["from"], r["period"]["to"]),
                 "proyectos: %s" % (", ".join(r["projects"]) if isinstance(r["projects"], list) else r["projects"]),
                 "anonimizado: %s" % ("sí" if r["anonymized"] else "no"), "formato: %d" % r["format_version"], "---", "",
                 "# Informe de uso de Claude Code", "", "## 0. Instrucciones para la IA", "", AI_PROMPT, "", "## 1. Resumen", ""):
        add(line)
    rows = []
    for k, label in LABELS.items():
        cur = fmt(k, s[k])
        if prev:
            pv = prev[k]
            delta = "—"
            if k in PCT and isinstance(pv, (int, float)):
                delta = "%+.1f pp" % (100 * (s[k] - pv))
            elif isinstance(pv, (int, float)) and pv:
                delta = "%+.0f %%" % (100 * (s[k] - pv) / pv)
            rows.append((label, cur, fmt(k, pv), delta))
        else:
            rows.append((label, cur))
    add(table(("Indicador", "Periodo", "Periodo anterior", "Variación") if prev else ("Indicador", "Periodo"), rows))
    add("")
    if not prev:
        add("_Sin periodo anterior comparable._")
        add("")
    if s["cost_coverage"] < 0.9:
        add("_El coste solo se conoce para las peticiones registradas por la telemetría (%s de los mensajes); el resto cuenta como 0._" % pct(s["cost_coverage"]))
        add("")

    add("## 2. Hallazgos detectados")
    add("")
    if not r["findings"]:
        add("Las reglas automáticas no han encontrado nada que supere sus umbrales en este periodo.")
        add("")
    for f in r["findings"]:
        add("### %s · %s · severidad %s" % (f["id"], f["title"], f["severity"]))
        add("")
        add("- **Evidencia:** %s" % f["evidence"])
        if f["recommendation"]:
            add("- **Recomendación:** %s" % f["recommendation"])
        imp = []
        if f.get("impact_usd"):
            imp.append("≈ %s" % usd(f["impact_usd"]))
        if f.get("impact_tokens"):
            imp.append("%s de tokens" % tok(f["impact_tokens"]))
        if f.get("impact_count"):
            imp.append("%d caso%s" % (f["impact_count"], "" if f["impact_count"] == 1 else "s"))
        if imp:
            add("- **Impacto en el periodo:** %s" % ", ".join(imp))
        if f["sessions"]:
            add("- **Sesiones de ejemplo:** %s" % ", ".join("`%s`" % x for x in f["sessions"]))
        add("")

    add("## 3. Coste por origen y modelo")
    add("")
    add(table(("Origen", "Mensajes", "Coste", "% coste", "Coste/mensaje", "Salida/mensaje", "Modelos principales",
               "Coste en comandos", "Coste fuera de comandos", "Modelos fuera de comandos"),
              [(a["agent"], a["messages"], usd(a["cost_usd"]), pct(a["cost_share"]), usd4(a["cost_per_message"]), tok(a["output_per_message"]),
                ", ".join(a["top_models"]), usd(a["cost_in_commands"]), usd(a["cost_outside_commands"]),
                ", ".join(a["top_models_outside_commands"]) or "—") for a in t["agents"]]))
    add("")
    add(table(("Modelo", "Mensajes", "Coste", "% coste", "Tokens", "$ por M tokens", "Acierto de caché", "Con coste conocido"),
              [(m["model"], m["messages"], usd(m["cost_usd"]), pct(m["cost_share"]), tok(m["tokens"]), "%.2f" % m["usd_per_mtok"],
                pct(m["cache_hit"]), pct(m["cost_coverage"])) for m in t["models"][:10]]))
    add("")
    if len(t["projects"]) > 1:
        add(table(("Proyecto", "Mensajes", "Coste"), [(p["project"], p["messages"], usd(p["cost_usd"])) for p in t["projects"][:10]]))
        add("")

    add("## 4. Herramientas")
    add("")
    add(table(("Herramienta", "Llamadas", "Errores", "Tasa", "Error más frecuente"),
              [(x["tool"], x["calls"], x["errors"], pct(x["error_rate"]), x["main_error"] or "—") for x in t["tools"][:15]]))
    if len(t["tools"]) > 15:
        add("")
        add("_Y %d herramientas más con menos llamadas._" % (len(t["tools"]) - 15))
    add("")
    add("Errores por herramienta, clase y modelo (los 15 grupos más frecuentes; `user_rejected`, `plan_rejected`, `permission_rule`, `hook_blocked`, `aborted` y `command_failed` no son fallos evitables):")
    add("")
    add(table(("Herramienta", "Clase de error", "Modelo", "Errores", "Llamadas de esa herramienta con ese modelo", "Tasa"),
              [(x["tool"], x["error_class"], x["model"], x["errors"], x["calls_tool_model"], pct(x["rate"])) for x in t["tool_errors"][:15]]))
    add("")
    health = sorted(t["model_health"].items(), key=lambda kv: -kv[1]["messages"])[:10]
    if health:
        add("Salud por modelo (errores evitables):")
        add("")
        add(table(("Modelo", "Mensajes", "Llamadas", "Errores evitables", "Tasa", "Herramienta que más falla"),
                  [(m, h["messages"], h["tool_calls"], h["tool_errors"], pct(_rate(h["tool_errors"], h["tool_calls"])),
                    ("%s (%d de %d)" % (h["tools"][0]["tool"], h["tools"][0]["errors"], h["tools"][0]["calls"])) if h["tools"] else "—")
                   for m, h in health]))
        add("")
    tr = t["turns"]
    add("Llamadas por turno: mediana %d, p90 %d, p95 %d, máximo %d, en %d turnos con herramientas. Turnos con llamadas repetidas: %d. "
        "Turnos con 3 o más errores evitables seguidos: %d. Turnos de más de %d llamadas: %d." % (
            tr["p50"], tr["p90"], tr["p95"], tr["max"], tr["turns_with_tools"], len(tr["loops"]), len(tr["error_streaks"]), tr["long_limit"], len(tr["long_turns"])))
    add("")

    add("## 5. Contexto y caché")
    add("")
    c = t["context"]
    add("- Compactaciones: %d (%d automáticas, %d con `/compact`) en %d sesiones; %d sesiones con dos o más." % (
        c["compactions"], c["auto"], c["manual"], c["sessions_with_compaction"], len(c["sessions_2plus"])))
    add("- Contexto del primer mensaje de cada sesión (instrucciones, CLAUDE.md y herramientas): mediana %s, p90 %s, en %d sesiones." % (
        tok(c["initial_context_p50"]), tok(c["initial_context_p90"]), c["initial_context_sessions"]))
    add("- El acierto de caché por modelo está en la sección 3.")
    add("")

    e = t["events"]
    add("## 6. Effort, origen de las llamadas y herramientas (eventos de telemetría)")
    add("")
    if not e["days_with_events"]:
        add("_Sin eventos de telemetría en el periodo (Loki guarda 30 días y el almacén propio empieza el día que se activa)._")
    else:
        add("_Mismo periodo que el resto del informe%s. Hay eventos en %d días; la telemetría empieza el %s%s._" % (
            " y solo las sesiones de los proyectos elegidos" if e.get("filter") == "project"
            else "; sin filtro de proyecto, incluye también sesiones cuyas conversaciones no están en esta máquina",
            e["days_with_events"], e["first_day"], "" if e["persistent_store"] else " (sin volumen: se pierde al reiniciar)"))
        add("")
        add("_Peticiones con eventos: %d, por %s. Las secciones 1 a 5 cuentan %s: solo los mensajes que quedan en las conversaciones. "
            "La diferencia son llamadas de fondo (sugerencias, títulos, compactación) y llamadas hechas dentro de herramientas, "
            "que no dejan mensaje en la conversación. Los modelos sin ajuste de effort (como Haiku) salen con «—»._" % (
                e.get("requests", 0), usd(e.get("cost_usd", 0)), usd(s["cost_usd"])))
        add("")
        add(table(("Modelo", "Effort", "Peticiones", "Coste", "Coste/petición", "Salida/petición"),
                  [(x["model"], x["effort"], x["requests"], usd(x["cost_usd"]), usd4(x["cost_per_request"]), tok(x["output_per_request"])) for x in e["effort"][:12]]))
        add("")
        add(table(("Origen (query_source)", "Tipo", "Peticiones", "Coste", "% coste"),
                  [(x["query_source"], x["kind"], x["requests"], usd(x["cost_usd"]), pct(x["cost_share"])) for x in e["sources"][:10]]))
        add("")
        if e["tool_bytes"]:
            add(table(("Herramienta", "Resultados", "Media devuelta", "Máximo", "Total"),
                      [(x["tool"], x["results"], kb(x["avg_bytes"]), kb(x["max_bytes"]), kb(x["total_bytes"])) for x in e["tool_bytes"][:12]]))
            add("")
        if e["decisions"]:
            add(table(("Herramienta", "Decisión", "Origen", "Veces"), [(x["tool"], x["decision"], x["source"], x["count"]) for x in e["decisions"][:15]]))
            add("")

    add("## 7. Skills y comandos")
    add("")
    if t["skills"]:
        add(table(("Tipo", "Nombre", "Usos", "Coste", "Coste por uso", "Tokens por uso"),
                  [("skill" if x["kind"] == "skill" else "comando", x["name"], x["activations"], usd(x["cost_usd"]), usd4(x["cost_per_activation"]),
                    tok(x["tokens_per_activation"])) for x in t["skills"]]))
        add("")
        add("El coste de un comando es el del turno que lanzó; el de una skill, el de los mensajes que Claude Code le atribuye. Son cotas superiores.")
        twice = sorted({x["name"] for x in t["skills"] if x["same_name_as_other_kind"]})
        if twice:
            add("Aparecen como skill y como comando a la vez: %s." % ", ".join("`%s`" % n for n in twice))
    else:
        add("No se usaron skills ni comandos en el periodo.")
    add("")
    cfg = r["config"]
    if cfg["commands"]:
        add("Comandos instalados:")
        add("")
        add(table(("Comando", "Modelo fijado", "Último cambio", "Usos en el periodo"),
                  [(x["name"], x["model"] or "—", x["changed"] or "—", x["uses"]) for x in cfg["commands"]]))
        add("")
    if cfg["skills"]:
        add("Skills instaladas:")
        add("")
        add(table(("Skill", "Último cambio", "Usos en el periodo"), [(x["name"], x["changed"] or "—", x["uses"]) for x in cfg["skills"]]))
        add("")
    add("_%s_" % cfg["note"])
    add("")

    add("## 8. Interacción")
    add("")
    i = t["interaction"]
    add("- Respuestas interrumpidas: %d; en %d se volvió a escribir en menos de dos minutos." % (i["aborted"], i["aborted_quick_retry"]))
    add("- Planes propuestos: %d; rechazados: %d." % (i["plans"], i["plans_rejected"]))
    add("- Turnos por sesión: mediana %d, p90 %d." % (i["user_messages_per_session_p50"], i["user_messages_per_session_p90"]))
    add("- Subagentes: usados en %d sesiones, %s del coste conocido." % (i["subagent_sessions"], pct(i["subagent_cost_share"])))
    add("")

    add("## 9. Glosario y limitaciones")
    add("")
    for line in (
        "- **Coste:** el que calcula Claude Code a precio de API para cada petición, casado con la conversación por su identificador. Solo existe desde que se activó la telemetría; con suscripción es un coste equivalente.",
        "- **Turno:** lo que ocurre desde un mensaje del usuario hasta el siguiente.",
        "- **Origen:** hilo principal o subagentes según la conversación; en la sección 6, el `query_source` de la telemetría, que distingue además las llamadas de fondo.",
        "- **Impacto ≈ $:** en errores y repeticiones, número de llamadas por el coste medio de una llamada con coste conocido; en concentración de coste, lo que sobra respecto al coste por mensaje del resto; en effort, lo que habrían costado esas peticiones al coste medio de un effort menor. Son órdenes de magnitud.",
        "- **Clases de error:** se obtienen del texto de cada resultado de herramienta, que no se guarda ni aparece aquí.",
        "- **Sesiones de ejemplo:** el detalle está en `http://localhost:9100/session/<id>`, solo en la máquina que ejecuta la pila.",
        "- Fechas en UTC. Generado en %.1f s." % r["build_seconds"]):
        add(line)
    add("")
    return "\n".join(L)


def render_json(r):
    return json.dumps(r, ensure_ascii=False, indent=2)
