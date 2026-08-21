# Mediciones y calibración (ítem #17)

Los tres números que el PRD y el `TECH-DESIGN.md` dejaron explícitamente como
**suposiciones**, ahora medidos. Reproducir con:

```
FIXTURES_PARIDAD=<recurso> uv run python -m tools.medicion --repeticiones 15
```

## Corrida de referencia

| | |
|---|---|
| Fecha | 2026-08-20 |
| Máquina | Windows Server 2019 10.0.17763, 16 núcleos lógicos, 96 GB RAM |
| Python | 3.12.0, `uv.lock` del repositorio |
| Entrada real | par 01 del manifiesto de paridad (31 registros procesables) |

**Estas mediciones no son de producción.** Salen de la máquina de desarrollo,
que además es compartida. La instancia real no existe todavía (prerrequisito
#0 del backlog) y su decisión pendiente —contenedor Linux o servicio Windows
nativo— cambia tanto la RAM disponible como el costo de arranque del proceso.
Sirven para dimensionar, para descartar sorpresas de orden de magnitud y para
reemplazar tres suposiciones por tres números. No sirven como el valor final
de producción.

## 1. Costo de arranque del proceso hijo

ADR 0012 fuerza `spawn` en las dos plataformas, así que el intérprete
reimporta el árbol de módulos **en cada petición**. El `TECH-DESIGN.md` lo
estimaba en "cientos de milisegundos" y lo marcaba como suposición.

| Medición | p50 | p95 |
|---|---|---|
| Antes de la partición | 877 ms | 1002 ms |
| **Después de la partición** | **428 ms** | **517 ms** |

**Hallazgo de la primera corrida: ~80 % del costo de importación del hijo era
FastAPI, que el hijo no usa.** El hijo no sirve HTTP. FastAPI entraba por dos
puertas: `app/core/errores.py`, que importaba `FastAPI`/`Request`/
`JSONResponse` para registrar el manejador —trabajo del padre— y del que
cuelga todo el vocabulario de errores; y `app/core/ejecucion.py`, que además
de contener el objetivo de `spawn` albergaba la mitad de admisión, con su
middleware ASGI y su lectura de configuración por pydantic-settings.

**La partición se hizo** (ver "Optimización aplicada", más abajo). La cadena
del hijo quedó en biblioteca estándar más openpyxl:

| Pieza | Antes | Después |
|---|---|---|
| Cadena del hijo (`import app.core.ejecucion`) | 662 ms | **283 ms** |
| └ `openpyxl`, dentro de la cadena | 279 ms | 239 ms |
| `fastapi` | 520 ms, **dentro** | 478 ms, **fuera** |
| Intérprete pelado (referencia) | 42 ms | 37 ms |

Nota sobre el `TECH-DESIGN.md`: su versión de este riesgo dice que el
intérprete reimporta "el árbol de módulos **con pandas adentro**". Eso dejó
de ser cierto en el ítem #16, que eligió openpyxl justamente por este costo.
La medición confirma la decisión: `import pandas` sólo cuesta ~590 ms en esta
máquina, así que habría **duplicado** el arranque del hijo.

## 2. Latencia de punta a punta

Requisito del PRD: **p95 ≤ 15 segundos** para `Contado_Carga`, medido de
punta a punta en el servicio. Petición HTTP completa —multipart, token,
admisión, hijo dedicado, empaquetado y respuesta— por la aplicación ASGI
real. Queda fuera el transporte de red, que no es tiempo del servicio.

| Entrada | p95 antes | **p95 después** | Margen contra 15 s |
|---|---|---|---|
| **Par 01 real, 31 registros** | 1059 ms | **586 ms** | 26× |
| Sintético, 100 registros | 1109 ms | **662 ms** | 23× |
| Sintético, 1 000 registros | 1900 ms | **1439 ms** | 10× |
| Sintético, 5 000 registros | 5335 ms | **4903 ms** | 3,1× |

**El requisito se cumple con holgura.** Sobre el único archivo real que
existe hoy, el p95 es de ~1 s contra un techo de 15 s.

Dos lecturas que conviene no perder:

- **Para archivos realistas el costo es casi todo arranque.** A 31 registros
  el trabajo real son 62 ms; todo el resto es `spawn` más imports. Optimizar
  el procesamiento no movería la aguja; optimizar el arranque sí, y por eso
  se optimizó el arranque.
- **El escalado es lineal en registros y sin sorpresas.** 5 000 registros
  —160 veces el archivo real— siguen bajo los 5 s. El techo de 15 s se
  alcanzaría alrededor de los 15 000 registros, un extracto muy por encima de
  lo que el proceso manual produce.

## 3. Huella de memoria del hijo

Medida desde adentro del proceso, en tres momentos.

Después de la partición:

| Entrada | Base | + árbol | + datos | Pico | Pico antes |
|---|---|---|---|---|---|
| Par 01 real, 31 registros | 18,0 MB | 8,7 MB | 1,3 MB | **28,0 MB** | 45,7 MB |
| Sintético, 100 registros | 17,7 MB | 8,9 MB | 1,1 MB | 27,8 MB | 45,9 MB |
| Sintético, 1 000 registros | 17,7 MB | 8,9 MB | 2,8 MB | 29,5 MB | 47,0 MB |
| Sintético, 5 000 registros | 17,9 MB | 8,9 MB | 6,7 MB | **33,5 MB** | 50,9 MB |

**El costo es casi todo fijo.** Base más árbol son ~27 MB que paga cualquier
ejecución por el solo hecho de existir; los datos agregan entre 1,1 y 6,7 MB.
Multiplicar por 160 el tamaño de la entrada sube el pico un 20 %.

Sacar FastAPI de la cadena del hijo bajó el árbol de módulos de 26,5 MB a
8,9 MB —un 66 % menos— y el pico de ~46 MB a ~28 MB. El ahorro de tiempo era
el buscado; el de memoria vino de regalo y cambia la calibración.

**Estos 51 MB no son el `PRESUPUESTO_DE_RAM_BYTES` de 256 MB de ADR 0021, y
no hay que confundirlos.** Aquél es el techo de *validación* —lo que se
rechaza como bomba ZIP antes de procesar— y sigue siendo el correcto para esa
tarea. Éste es el consumo *observado* de una ejecución legítima. Uno acota lo
que se admite; el otro dimensiona cuántas ejecuciones caben a la vez.

## 4. Concurrencia, y qué acota realmente `EJECUCIONES_MAX`

Entrada de 1 000 registros, `EJECUCIONES_MAX` abierto para medir degradación
y no admisión.

Después de la partición:

| Simultáneas | p50 | p95 | Rendimiento |
|---|---|---|---|
| 1 | 1374 ms | 1374 ms | 0,73 pet/s |
| 2 | 1368 ms | 1374 ms | 1,45 pet/s |
| 4 | 1488 ms | 1602 ms | 2,47 pet/s |
| 8 | 1557 ms | 1724 ms | 4,59 pet/s |

El rendimiento escala casi linealmente y la latencia se degrada poco. El
trabajo del hijo es CPU-bound —parsear un Excel—, así que **el techo lo ponen
los núcleos, no la RAM**: dieciséis ejecuciones consumirían ~536 MB, nada en
una máquina de 96 GB, pero pasado el número de núcleos subir el cupo sólo
reparte los mismos núcleos entre más peticiones.

### Valor calibrado

```
EJECUCIONES_MAX ≈ min( núcleos_lógicos,
                       (RAM_disponible_MB − 512) / 48,
                       32 )
```

- **48 MB por ejecución**: el pico medido de 33,5 MB, redondeado con margen.
- **512 MB reservados**: el proceso padre (uvicorn más la aplicación).
- **32**: el techo que ya impone el campo, porque por encima el limitador de
  hilos de anyio (40 por defecto) pasaría a ser la concurrencia real en vez
  de este parámetro.

**El valor por defecto pasa de 2 a 4.** El 2 original se justificaba
suponiendo que cada hijo podía llegar al presupuesto de 256 MB de ADR 0021,
o sea 512 MB en total. Con 33,5 MB medidos, cuatro ejecuciones consumen
~134 MB —una cuarta parte de lo que aquel valor ya daba por aceptable— y
duplican la capacidad. Es un valor fundado en medición y sigue siendo
conservador para una instancia chica.

**No se sube más porque la instancia no existe.** En esta máquina 16 anda
cómodo, pero elegir 16 sería calibrar contra el servidor de desarrollo. La
fórmula de arriba es lo que hay que aplicar cuando el prerrequisito #0 se
resuelva y se conozcan núcleos y RAM reales.

`TIMEOUT_EJECUCION` se deja en 60 s: contra los 4,9 s del peor caso medido
son más de 12× de margen, y sigue estrictamente por debajo del corte de
2 minutos del portal.

## Optimización aplicada

La partición que la sección 1 identificó se hizo, y son **dos**, no una.
Partir sólo `app/core/errores.py` no habría ahorrado nada: `app/core/
ejecucion.py` —el módulo que contiene el objetivo de `spawn`, y por lo tanto
el que se reimporta en cada petición— importaba FastAPI, Starlette y
pydantic-settings por su cuenta, para la mitad de admisión.

| Módulo | Qué se queda | Qué se fue |
|---|---|---|
| `app/core/errores.py` | vocabulario, sólo stdlib | → `app/core/errores_http.py`: mapa a códigos HTTP y manejador |
| `app/core/ejecucion.py` | plomería del hijo, sólo stdlib | → `app/core/admision.py`: semáforo, `admitir()`, middleware, 503 |

Ninguna firma pública cambió de forma y ningún comportamiento se movió: es
una partición de dependencias, no de contrato. La cadena del hijo quedó en
biblioteca estándar más openpyxl, y `tests/test_rendimiento.py` lo vigila en
un intérprete fresco —`sys.modules` es del proceso, y para cuando ese test
corre otras suites del mismo pytest ya importaron FastAPI—.

En una frase: **el arranque del hijo bajó a la mitad y su memoria a dos
tercios; el p95 sobre el archivo real pasó de 1059 ms a 586 ms.**

## Lo que sigue abierto

- **La instancia de producción** (prerrequisito #0). Hay que rehacer esta
  corrida ahí y aplicar la fórmula. En un contenedor Linux el costo de
  arranque puede diferir bastante del de Windows.
- **Sólo hay un archivo real**, de 31 registros. Los tamaños grandes de la
  tabla son sintéticos. Si los extractos reales resultan ser mucho mayores,
  la fila de 5 000 registros es la referencia pertinente.
- **Un segundo procesador real volvería a subir la cadena del hijo.** Cada
  módulo dado de alta en `app/registry.py` se reimporta en cada petición, lo
  use ese hijo o no. Con openpyxl ya pago el costo marginal es chico, pero un
  procesador que traiga una librería nueva y pesada se lo cobra a todas las
  ejecuciones. Es el precio de que el registro sea un literal, y la
  alternativa —importar por nombre dentro de `core/`— es justo lo que ADR
  0012 descarta.
