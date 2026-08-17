# Backlog: Servicio de Procesadores (FastAPI)

> **Alcance de este backlog.** Despieza el **ítem #9** del backlog maestro del Portal de Innovación
> (`L:\App_Portal\BACKLOG.md`) en specs implementables de este repositorio. Cada fila de la tabla es
> un ciclo de Spec-Driven Development, no el proyecto entero.
>
> La autoridad de arquitectura son los ADR: los heredados del portal (`L:\App_Portal\adrs\`, 0001 a
> 0007) y los propios de este repositorio (`adrs\`, 0011 a 0015). Ante cualquier discrepancia entre
> este documento y un ADR, **manda el ADR**. Este backlog no crea alcance: solo ordena lo que el
> `PRD.md` y el `TECH-DESIGN.md` ya establecen.

## Prerrequisitos externos

No son ítems de este repositorio y **ninguno se resuelve programando acá**. Bloquean el cierre del
ítem #9, no necesariamente su arranque.

| Prerrequisito | Dueño | Qué bloquea |
|---|---|---|
| **#0 — Infraestructura**: red interna con el endpoint inalcanzable desde fuera, y SQL Server provisionado con el usuario de privilegios acotados (`SELECT`, sin DDL ni escritura) | TI | Los ítems 5, 11 y 17. Además, decidir contenedor Linux vs. servicio Windows nativo define si hay techo real de RAM para el proceso hijo |
| **#2 — Esquema y migraciones del portal** | Portal (Prisma) | El ítem 5: sin la tabla `procesador` no hay contrato que leer |
| **#10 — Tratamiento de errores y del 503 en el portal** | Portal | Nada de acá. Va en sentido inverso: este servicio **define** el vocabulario (ítem 3) y el portal lo consume |

## Backlog

| # | Ítem | Alcance | Depende de | Contexto extra requerido |
|---|---|---|---|---|
| 1 | Esqueleto del servicio y arranque seguro | FastAPI + configuración por entorno, `set_start_method("spawn", force=True)` antes de crear procesos o conexiones, fallo al iniciar si falta el token, health check | — | — |
| 2 | Autenticación por token de servicio | 401 antes de leer el cuerpo del request, comparación en tiempo constante, token ausente de logs, trazas y mensajes de error | #1 | — |
| 3 | Contrato de errores tipificados (ADR 0014) | Enum cerrado de 5 tipos + `contexto` con datos estructurados, sin texto destinado al usuario; 422 para los 4 corregibles, error de servidor para `clave_inexistente` | #1 | — |
| 4 | Interfaz `Procesador`, tipos de archivo y registry | ABC con `validar`/`procesar` sobre listas, `ArchivoEntrada`/`ArchivoSalida`, registry `dict[str, Procesador]` | #3 | — |
| 5 | Espejo de solo lectura de SQL Server (ADR 0013) | SQLAlchemy Core sobre pyodbc, `SELECT` parametrizado por `clave_procesador` activo, sin cache, error controlado si la base no responde | #1, #3 | — |
| 6 | Recepción y ciclo de vida de temporales | Escritura de entradas a disco, nombres saneados (path traversal, acentos, duplicados), `try/finally` que no deja sobrevivir ningún temporal en ningún camino | #1, #3 | — |
| 7 | Validaciones de contrato y defensa de memoria | Cantidad, formato, tamaño por archivo y suma total, corte leyendo el stream cuando `Content-Length` falta o miente, y tamaño descomprimido declarado contra el límite de RAM (anti zip-bomb) | #3, #5, #6 | — |
| 8 | Admisión acotada y ejecución en proceso dedicado (ADR 0012) | Semáforo no bloqueante con 503 inmediato sin encolar, `Process` en spawn, resultado por `Pipe`, `join(TIMEOUT_EJECUCION)` con `kill()` real, cupo liberado en éxito, error, excepción y timeout | #3, #4, #6 | — |
| 9 | Empaquetado de la salida | Una salida se entrega tal cual con su MIME y nombre; más de una se comprime en ZIP sin rutas embebidas; cero salidas es error de contenido y nunca sale un ZIP a medias | #3, #6 | — |
| 10 | Pipeline común: los 9 pasos en orden | Orquesta los pasos 0 a 9, es el dueño del `try/finally` y no contiene ninguna referencia a un procesador concreto | #4, #5, #6, #7, #8, #9 | — |
| 11 | Chequeo de arranque registry ↔ base de datos | La tabla de tres situaciones del Technical Design: falla por clave sin fila, advierte por fila inactiva y por fila sin registry; mensaje distinto para "no pude conectar" y "el registry no coincide" | #4, #5 | — |
| 12 | Procesador passthrough y su ruta cáscara | Módulo mínimo que devuelve una salida marcada, más la variante multi-archivo que produce ZIP. Es el que prueba la tubería completa navegador → portal → FastAPI → descarga | #10 | — |
| 13 | Invariantes de arquitectura verificados en CI | Comprobación de que `core/` no importa `procesadores/`, de que ningún procesador importa `core.db` ni transitivamente, y test de que **cada** ruta delega en el pipeline | #12 | — |
| 14 | Logging operativo estructurado | Por ejecución: clave, cantidad y tamaño de archivos, duración, resultado y tipo de error — **más los rechazos por saturación**, sin los cuales un `EJECUCIONES_MAX` mal calibrado se ve igual que un servicio caído | #10 | — |
| 15 | Infraestructura de fixtures de paridad (ADR 0015) | `manifiesto.toml` con `sha256` y bloque de procedencia obligatorio por par, ubicación por `FIXTURES_PARIDAD`, fallo en CI si faltan y salto solo en local con aviso explícito | #1 | — |
| 16 | Migración de `Contado_Carga` | Módulo + ruta cáscara: columnas leídas por nombre, fin de línea del TXT fijado explícitamente, descartes contados y reportados, cero filas procesadas como error de contenido, ninguna excepción tragada. Validado contra los 3 pares reales | #12, #15 | **Sí — ver abajo** |
| 17 | Medición y calibración | p95 de `Contado_Carga` medido de punta a punta, costo de arranque del proceso hijo medido y documentado dentro del presupuesto de 15 s, y `EJECUCIONES_MAX` ajustado con datos reales en vez de estimación | #16 | Requiere la instancia del prerrequisito #0 |

## Contexto extra requerido — ítem 16

Antes de generar la spec del ítem 16, compartí tu documentación de reglas de negocio de este dominio,
si la tenés. Concretamente hacen falta cuatro cosas:

1. **Las reglas de `Contado_Carga.py`**: el `MAPEO_PLAZAS` con el texto exacto de las 10 plazas, y el
   formateo del volcado por tipo y magnitud — `round(abs(importe), 2)` para montos y la rama que
   imprime sin decimales los números mayores a `1000000000` por asumir que son identificadores.
2. **Los 3 pares reales de entrada/salida**, colocados en el recurso compartido con su manifiesto
   completo (hashes y procedencia).
3. **La confirmación del fin de línea del TXT** con el sistema que lo consume. El Technical Design lo
   registra explícitamente como **no confirmado**: hoy se hereda de la plataforma, CRLF en Windows y
   LF en Linux.
4. **La revisión de los 3 pares antes de congelar sus hashes.** Si alguno contiene una fila que el
   script viejo descartó en silencio, la paridad byte a byte y el endurecimiento obligatorio se
   contradicen, y hay que decidir explícitamente cuál de los dos requisitos manda.

## Qué no está en este backlog, y por qué

- **El mapeo de errores y del 503 en el portal.** Es el ítem #10 del backlog maestro, en otro
  repositorio. Este servicio define el vocabulario y lo emite; el portal lo consume, lo mapea al
  banner y al `evento_uso`, e implementa el fallback obligatorio y el caso propio del 503.
- **Los otros dos procesadores reales del ítem #12.** No tienen reglas de negocio documentadas
  todavía. No bloquean nada: el pipeline, el passthrough y `Contado_Carga` avanzan sin ellos.
- **El panel de administración del catálogo `procesador`.** Es el ítem #6 del backlog maestro, del
  portal. Este servicio solo lee esa fila.

## Cómo usar este backlog

Cada ítem es una spec independiente. Al implementarlo, arrancá un ciclo de Spec-Driven Development
(`sdd-new` o el flujo equivalente de tu harness) usando **ese ítem** como el "change" — no el
proyecto completo. Si la columna "Contexto extra requerido" tiene algo, compartilo como contexto al
generar la spec de ese ítem.

El orden es por **dependencia**, no por prioridad ni por interés. Un ítem que otros necesitan va
primero aunque sea el menos vistoso: los ítems 1 a 9 construyen las piezas del pipeline, el 10 las
ensambla, y recién el 12 permite ver la tubería funcionando de punta a punta.
