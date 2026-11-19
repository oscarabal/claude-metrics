"""Reduce a Claude Code tool error to a class.

The text comes from the `tool_result` blocks of the conversation files. It is read only to pick a
class and is never stored or published. Same classes as the OpenCode module where they mean the
same, plus a few that only Claude Code has (plan rejections, hooks, MCP).
"""
import re

# (class, pattern) in order; the first match wins
_RULES = [
    ("user_rejected", r"doesn't want to proceed|user rejected|was rejected|user denied|user declined|user doesn't want to take"),
    ("permission_rule", r"permission to use .* (?:has been|was) denied|denied by (?:your )?permission|not allowed by (?:your )?settings|requires approval"
                        r"|denied by a built-in claude code safety check|auto mode classifier"),
    ("hook_blocked", r"blocked by (?:a |the )?hook|hook .*(?:blocked|denied)|pretooluse"),
    ("missing_dependency", r"is not installed|cannot find module|err_module_not_found|modulenotfounderror|no module named"),
    ("tool_misuse", r"<tool_use_error>blocked:|no such tool available|eisdir|requires a prior|take a new screenshot|no preview is open"
                    r"|shows a local file, not a web page|rejected the pattern|also needs \"scope\""),
    ("aborted", r"interrupted by user|request interrupted|aborted"),
    ("read_before_write", r"has not been read yet|read it first|must read .* before|file has been modified since"),
    ("old_string_missing", r"string to replace not found|old_string .*not found|could not find"),
    ("multiple_matches", r"found \d+ matches|multiple matches|replace_all is false"),
    ("no_change", r"no changes to make|exactly the same"),
    ("not_found", r"does not exist|no such file|file not found|cannot find path|enoent|not found:"),
    ("output_too_large", r"exceeds maximum allowed|too large|too long|maximum .*tokens|output limit"),
    ("schema_error", r"inputvalidationerror|invalid input|invalid arguments|required parameter|is missing|expected .* received"),
    ("mcp_error", r"mcp error|mcp server|-326\d\d|json-?rpc"),
    ("shell_error", r"is not recognized as|commandnotfoundexception|parsererror|parameterbindingexception|cannot validate argument|syntax error near|command not found"
                    r"|unexpected eof while looking for matching"),
    ("timeout", r"timed out|timeout"),
    ("access_denied", r"access is denied|permission denied|eacces|eperm|unauthorized|forbidden|\b40[13]\b"),
    ("network", r"econnrefused|enotfound|fetch failed|network|status code [45]\d\d|getaddrinfo|socket hang up"),
    ("command_failed", r"exit code \d+|exited with|non-zero"),
]
_COMPILED = [(name, re.compile(pat, re.I | re.S)) for name, pat in _RULES]

# Classes that are the user's own decisions or normal work, not something to prevent
NOT_AVOIDABLE = {"user_rejected", "plan_rejected", "aborted", "permission_rule", "hook_blocked", "command_failed"}

ADVICE = {
    "not_found": ("Rutas inexistentes",
                  "Añade a CLAUDE.md una regla como «No adivines rutas: localiza los ficheros con Glob o Grep antes de leerlos». "
                  "Si se concentra en un proyecto, describe su estructura de carpetas en el CLAUDE.md del proyecto."),
    "old_string_missing": ("El texto a sustituir no está en el fichero",
                           "Regla: «Copia old_string literalmente de una lectura reciente del fichero, con la misma indentación». "
                           "Si se concentra en un modelo, revisa si ese modelo edita peor."),
    "multiple_matches": ("El texto a sustituir aparece varias veces",
                         "Regla: «Incluye en old_string contexto suficiente para que sea único, o usa replace_all a propósito»."),
    "read_before_write": ("Edición sin lectura previa", "Regla: «Lee siempre un fichero, o vuelve a leerlo si ha cambiado, antes de editarlo»."),
    "no_change": ("Ediciones sin cambios", "El modelo intenta ediciones vacías; suele indicar que no ha comprobado el resultado anterior."),
    "schema_error": ("Llamadas mal formadas",
                     "El modelo no respeta el esquema de la herramienta. Si se concentra en un servidor MCP, revisa su versión o desactívalo."),
    "output_too_large": ("Salida demasiado grande",
                         "Acota la lectura (offset y limit), filtra la salida de los comandos (head, Select-Object -First) o delega en un subagente."),
    "mcp_error": ("Errores de servidores MCP", "Revisa el servidor MCP afectado (conexión, versión, credenciales) o desactívalo si no lo usas."),
    "shell_error": ("Errores de shell",
                    "Indica en CLAUDE.md la shell disponible (PowerShell en Windows) y los comandos equivalentes que debe usar; "
                    "muchos fallos vienen de sintaxis de bash en PowerShell o al revés."),
    "missing_dependency": ("Falta una herramienta o librería",
                           "Instala lo que falta (por ejemplo poppler para leer PDF, o el paquete de npm o pip que se pide) "
                           "o indica en CLAUDE.md qué herramientas hay disponibles para que no las dé por supuestas."),
    "tool_misuse": ("Uso incorrecto de herramientas",
                    "El modelo llama a una herramienta de forma que la propia herramienta rechaza (esperas con sleep, "
                    "rutas que son carpetas, pasos previos que faltan). Si se repite con un modelo, prueba otro para esa tarea."),
    "timeout": ("Tiempo agotado", "Divide las operaciones largas o lánzalas en segundo plano."),
    "access_denied": ("Acceso denegado", "Revisa credenciales o permisos del recurso al que accede la herramienta."),
    "network": ("Errores de red", "Revisa la conectividad o la URL que se pide."),
    "command_failed": ("Comandos que terminan con error",
                       "Es normal en pruebas y compilaciones; solo preocupa si se repite el mismo comando sin cambios (ver bucles)."),
    "user_rejected": ("Rechazado por el usuario", ""),
    "plan_rejected": ("Plan rechazado", ""),
    "permission_rule": ("Bloqueado por una regla de permisos", ""),
    "hook_blocked": ("Bloqueado por un hook", ""),
    "aborted": ("Interrumpido", ""),
    "other": ("Otros errores", "Revisa los casos en el detalle de las sesiones."),
}


_EXIT = re.compile(r"\s*exit code \d+", re.I)
_BY_NAME = dict(_COMPILED)


def classify(error, tool=""):
    text = error or ""
    if _EXIT.match(text):
        # A command that ran and failed: its output can mention anything (timeouts, missing files),
        # so only a missing dependency or a shell syntax problem says more than "the command failed"
        for name in ("missing_dependency", "shell_error"):
            if _BY_NAME[name].search(text):
                return name
        return "command_failed"
    for name, rx in _COMPILED:
        if rx.search(text):
            if name == "user_rejected" and tool == "ExitPlanMode":
                return "plan_rejected"
            return name
    if tool == "ExitPlanMode":
        return "plan_rejected"  # the only way ExitPlanMode fails is the user not accepting the plan
    if tool.startswith("mcp__"):
        return "mcp_error"
    return "other"
