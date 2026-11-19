# Guía del dashboard de Claude Code

Telemetría de Claude Code · capturas del 16/11/2026

Qué dibuja cada panel del dashboard «Claude Code», qué pregunta responde y cómo se lee. Es un único dashboard organizado en cuatro filas (Resumen, Reparto del gasto, Sesiones, skills y prompts, y Por hora). Filtra por proyecto con el selector de arriba a la izquierda y usa el selector de tiempo de Grafana, así que vale cualquier rango de fechas. Sustituye a los tres dashboards anteriores (Uso y coste, Eventos y Sesiones).

Los paneles de sesiones y skills salen del índice de conversaciones, no de la telemetría, y cuentan los días en UTC. Las tablas de prompts más caros y de herramientas salen de Loki, que guarda 30 días: con un rango de 30 días justos Grafana puede dar error, así que usa 29 o menos. El dashboard sigue la guía de estilos de los de OpenCode: cifras sin color de umbral, azul para el coste y morado para los tokens, barras en lugar de gráficos circulares, tokens en millones con sufijo «M» y totales en el pie de las tablas.

## Resumen y reparto del gasto

### Resumen

| Panel | Tipo | Qué muestra | Qué aporta |
| --- | --- | --- | --- |
| Coste estimado | Stat | Gasto en dólares del periodo. | La cifra que más importa a presupuesto; se lee junto a los tokens para ver el precio medio. |
| Tokens | Stat | Todos los tokens del periodo (entrada, salida y caché), en millones. | El volumen global de un vistazo; sirve para comparar un día o un proyecto con otro. |
| USD por millón de tokens | Stat | El coste dividido entre los tokens. | El precio efectivo; baja con modelos más baratos o más caché. |
| Acierto de caché | Stat | Lectura de caché entre lectura, creación de caché y entrada. | Cuánto contexto se reutiliza en lugar de rehacerse. |
| Sesiones con actividad | Stat | Sesiones distintas que gastaron tokens dentro del periodo. | Distingue pocas sesiones muy caras de muchas baratas. Una sesión abierta sin uso no cuenta. Pulsa la cifra para ver la lista de sesiones. |
| Evolución diaria | Barras y línea | El coste de cada día (barras, eje izquierdo) y los tokens en millones (línea, eje derecho) del rango elegido. | La tendencia: días caros y si el coste y el volumen suben juntos. |
| Coste por effort | Barras | Qué parte del gasto corresponde a cada nivel de esfuerzo de razonamiento. | Muestra cuánto cuesta trabajar siempre en un nivel alto; es la palanca más directa para bajar el gasto. |
| Coste por proyecto | Barras | Coste del periodo por proyecto, con el mapa de sesiones. | Atribuye el gasto a proyectos. |

### Reparto del gasto

| Panel | Tipo | Qué muestra | Qué aporta |
| --- | --- | --- | --- |
| Cuota de coste y de tokens por modelo | Barras agrupadas | Para los diez modelos con más coste, su parte del coste total y de los tokens totales; `Otros` suma el resto. | Una barra de tokens mucho más larga que la de coste es un modelo barato; al revés, caro. Sustituye al antiguo gráfico circular de coste por modelo. |
| Detalle por modelo y effort | Tabla | Coste del periodo para cada combinación de effort y modelo, con el total en el pie. | La cifra exacta detrás de los gráficos, para copiarla a un informe. |

## Sesiones, skills y prompts

La fila Por hora, plegada por defecto, se ve aquí desplegada.

| Panel | Tipo | Qué muestra | Qué aporta |
| --- | --- | --- | --- |
| Contexto de las sesiones | Tabla con barras | Para las sesiones con actividad dentro del periodo elegido (hasta las 30 más recientes, `CONTEXT_SESSIONS`), el porcentaje de la ventana de contexto en uso (barra, verde por debajo del 60 %, naranja hasta el 85 %, roja por encima), los tokens usados, los libres y el límite; pulsa una sesión para abrir su detalle. | Muestra lo cerca que está una sesión de su límite y de necesitar compactarse. |
| Uso de skills y comandos (veces) | Tabla con barras | Cada comando propio ejecutado y cada skill cargada en el periodo, con su nombre real, cuántas veces como comando (escrito por ti) y como skill (cargada por Claude). | Muestra qué skills y comandos se usan de verdad, también las que Claude carga solo. El coste de cada comando está en «Modelos y origen por comando». |
| Modelos y origen por comando | Tabla anidada | Una fila por comando con su coste total; al desplegarla, el coste de los turnos que lanzó separado por modelo y por origen: `sdk` es el hilo principal, `agent:...` son subagentes y `prompt_suggestion`, `compact` o `web_search_tool` son llamadas de fondo. | Responde a «qué modelos se usaron al lanzar este comando». Solo cuenta el turno del comando, no las respuestas posteriores. |
| Prompts más caros | Tabla | Cada prompt con su coste y su texto. Pulsar el identificador abre su línea de tiempo en Explore. Excluye los prompts redactados. | Pasa de «este prompt costó mucho» a «este fue el prompt». El texto solo existe en sesiones nuevas con `OTEL_LOG_USER_PROMPTS=1`. |
| Herramientas | Tabla con barras | Por herramienta: cuántas veces se llamó, cuántos bytes devolvió, esos bytes como tokens aproximados (bytes entre 4, en miles) y cuánto tardó de media. Los tokens son una estimación, no una medida, y no hay columna de coste porque la telemetría no lo relaciona con la herramienta. | Encuentra las herramientas que llenan el contexto (lo devuelto se relee en las llamadas siguientes) o que hacen esperar, y sirve para decidir qué recortar o desactivar. |

**Límite de contexto.** Claude Code no dice el tamaño de la ventana de un modelo. La barra supone 200k, o 1M cuando la sesión ya usó más de 200k. El valor real se define por modelo con `CONTEXT_LIMITS` en el fichero `.env`.

**Coste atribuido.** Es el de los mensajes que Claude Code marca como pertenecientes a la skill o al comando, y solo existe para las llamadas que registró la telemetría. Incluye todo lo que ocurre dentro, así que es una cota superior.

**Herramientas.** Los tokens aproximados son los bytes devueltos entre 4: una estimación, no una medida. No hay columna de coste porque la telemetría no relaciona el coste con la herramienta.

## Por hora

| Panel | Tipo | Qué muestra | Qué aporta |
| --- | --- | --- | --- |
| Tokens por modelo (por hora) | Barras por hora | Tokens de cada hora, separados por modelo, en millones. | Localiza las horas de más actividad y detecta si empieza a usarse un modelo nuevo. |
| Coste por modelo y effort (por hora) | Barras por hora | Coste de cada hora separado por modelo y nivel de esfuerzo. | Muestra qué horas fueron caras y con qué esfuerzo; une el reparto del coste con el reloj. |

## Mejoras

La fila «Mejoras» resume el informe de mejoras: lo que puedes cambiar (reglas en CLAUDE.md, modelo o *effort* por defecto, modelos fijados en comandos, reglas `allow` de permisos, hábitos al escribir prompts) para gastar menos y que el agente falle menos. Sirve también para comprobar, semanas después, si un cambio funcionó. El informe completo se abre en una pestaña nueva con el enlace **Informe de mejoras** de arriba a la derecha, con el rango y los proyectos elegidos, o pulsando las cifras de esta fila. En esa página las sesiones de ejemplo enlazan con su detalle, y los botones de arriba descargan el informe (.md), copian su Markdown u ocultan los nombres de proyecto antes de compartirlo.

| Panel | Tipo | Qué muestra | Qué aporta |
| --- | --- | --- | --- |
| Mejoras detectadas | Cifra | Hallazgos del informe en el rango y los proyectos elegidos. | Cuánto hay por mejorar. Es el mismo cálculo que el informe que se descarga; pulsa la cifra para abrirlo. |
| Impacto estimado | Cifra | Suma del impacto en dólares de esos hallazgos, a precio de API. | Un orden de magnitud; con suscripción es coste equivalente. |
| Errores evitables de herramientas | Cifra | Parte de las llamadas que fallaron en el rango, sin rechazos (también de planes), bloqueos, interrupciones ni comandos que terminan con error. | La salud general del uso de herramientas. |
| Compactaciones e interrupciones | Cifra doble | Compactaciones de contexto y respuestas interrumpidas en el rango. | Sesiones demasiado largas y prompts que arrancan mal. |
| Hallazgos | Tabla | Cada mejora detectada en el rango y los proyectos elegidos: severidad, regla, qué pasa, impacto, casos, recomendación y evidencia. | Qué cambiar, sin salir del dashboard. Los textos largos se leen pasando el ratón por la celda; las sesiones de ejemplo están en el informe. |
| Hallazgos por regla | Tabla | Hallazgos, cuántos de severidad alta e impacto, por regla, en el rango y los proyectos elegidos. | Qué tipo de mejora pesa más. |
| Errores evitables por herramienta y modelo | Tabla | Llamadas, errores y tasa de cada herramienta y modelo con algún fallo; naranja desde el 5 %, rojo desde el 15 %. | Dónde compensa una regla en CLAUDE.md o usar otro modelo. |
| Coste por mensaje de cada modelo, por semana | Líneas | Coste medio por mensaje de cada modelo, las últimas 13 semanas. | Comprueba el efecto de cambiar de modelo o de *effort*. |
| Errores evitables por herramienta, por semana | Líneas | Tasa de error semanal de las cinco herramientas con más fallos evitables. | Comprueba si una regla nueva reduce los fallos. |
| Bytes devueltos al contexto por herramienta | Tabla | Llamadas, total, media, máximo y tokens aproximados de lo que devuelve cada herramienta en el rango y los proyectos elegidos, según la telemetría. | Las herramientas que más llenan el contexto y provocan compactaciones. |

## Páginas de sesión

Se abren en otra pestaña desde la fila Sesiones y skills y desde la cifra de sesiones del Resumen. Las sirve `session-map` en `http://localhost:9100` y solo funcionan en la máquina de la pila.

| Página | Qué muestra |
| --- | --- |
| `/sessions` | La lista de las sesiones del periodo y el proyecto elegidos, con filtro de texto, columnas ordenables y el coste conocido de cada una. |
| `/session/<id>` | El título, el proyecto, la rama y la duración; el coste conocido (con cuántos mensajes lo tienen), los tokens, las herramientas, las compactaciones y los subagentes; el contexto como una barra dividida en entrada, caché leída, caché escrita y salida; un gráfico del contexto en cada mensaje con las compactaciones marcadas y otro del coste acumulado; y las tablas de modelos, skills y comandos, herramientas con sus fallos, compactaciones (tokens antes y después) y subagentes. |

El coste de las sesiones anteriores a la telemetría sale como «—»: es desconocido, no cero. Las páginas no muestran el texto de la conversación.

## Cómo leer las cifras

- **«Mil» son millones.** Grafana abrevia así en estos paneles: «49,9 Mil» son 49,9 millones de tokens y «20 Mil» en un eje son 20 millones. «K» son miles.
- **Las filas de métricas y de eventos no suman igual.** Las de Prometheus leen métricas acumuladas y las de eventos cuentan eventos de Loki. Para el mismo periodo las cifras pueden diferir un poco. Compara cada dashboard consigo mismo.
- **El coste es una estimación** que calcula el cliente a partir de los tokens, no la factura.
- **El texto de los prompts** solo existe para sesiones nuevas desde el 13/11/2026; los anteriores salen como `<REDACTED>` y la tabla de prompts los excluye.
- **Las skills propias** aparecen como `custom_skill` mientras no se active `OTEL_LOG_TOOL_DETAILS=1`.