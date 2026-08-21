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
| Ejecución completa con trabajo ~0 (`passthrough`, 1 byte) | 877 ms | 1002 ms |

La estimación era correcta en orden de magnitud: **~0,9 s por petición**, un
6 % del presupuesto de 15 s. De dónde sale, midiendo intérpretes frescos:

| Pieza | Mediana |
|---|---|
| Árbol completo (`import app.registry`) | 662 ms |
| └ `fastapi` | 520 ms |
| └ `openpyxl` | 279 ms |
| Intérprete pelado (referencia) | 42 ms |

**Hallazgo: ~80 % del costo de importación del hijo es FastAPI, que el hijo
no usa.** El hijo no sirve HTTP: sólo necesita `ErrorTipificado` y las clases
de error. FastAPI entra porque `app/core/errores.py` importa `FastAPI`,
`Request` y `JSONResponse` para registrar el manejador HTTP —trabajo del
proceso padre— y `app/core/interfaz.py` importa ese módulo por el
vocabulario de errores. La cadena entera se paga en cada petición.

Para el archivo real, el arranque es **~85 % del tiempo total de respuesta**.
Partir `app/core/errores.py` en vocabulario (sólo biblioteca estándar) y
manejador (FastAPI) recortaría alrededor de medio segundo por petición.
**No se hizo en este ítem**: el ítem #17 es medir y calibrar, y esa partición
toca el módulo que ADR 0014 define. Queda como decisión propuesta, con la
evidencia de arriba.

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

| Entrada | p50 | p95 | Margen contra 15 s |
|---|---|---|---|
| **Par 01 real, 31 registros** | 970 ms | **1059 ms** | 14× |
| Sintético, 100 registros | 971 ms | 1109 ms | 13× |
| Sintético, 1 000 registros | 1735 ms | 1900 ms | 8× |
| Sintético, 5 000 registros | 5093 ms | 5335 ms | 2,8× |

**El requisito se cumple con holgura.** Sobre el único archivo real que
existe hoy, el p95 es de ~1 s contra un techo de 15 s.

Dos lecturas que conviene no perder:

- **Para archivos realistas el costo es casi todo arranque.** A 31 registros,
  ~0,9 s de los ~1,06 s son `spawn` más imports; el trabajo real son 63 ms.
  Optimizar el procesamiento no movería la aguja; optimizar el arranque sí.
- **El escalado es lineal en registros y sin sorpresas.** 5 000 registros
  —160 veces el archivo real— siguen a 5,3 s. El techo de 15 s se alcanzaría
  alrededor de los 15 000 registros, un extracto muy por encima de lo que el
  proceso manual produce.

## 3. Huella de memoria del hijo

Medida desde adentro del proceso, en tres momentos.

| Entrada | Base | + árbol de módulos | + datos | Pico |
|---|---|---|---|---|
| Par 01 real, 31 registros | 17,7 MB | 26,4 MB | 1,5 MB | **45,7 MB** |
| Sintético, 100 registros | 17,7 MB | 26,8 MB | 1,4 MB | 45,9 MB |
| Sintético, 1 000 registros | 17,7 MB | 26,6 MB | 2,8 MB | 47,0 MB |
| Sintético, 5 000 registros | 17,8 MB | 26,8 MB | 6,2 MB | **50,9 MB** |

**El costo es casi todo fijo.** Base más árbol son ~44 MB que paga cualquier
ejecución por el solo hecho de existir; los datos agregan entre 1,5 y 6 MB.
Multiplicar por 160 el tamaño de la entrada sube el pico un 11 %.

**Estos 51 MB no son el `PRESUPUESTO_DE_RAM_BYTES` de 256 MB de ADR 0021, y
no hay que confundirlos.** Aquél es el techo de *validación* —lo que se
rechaza como bomba ZIP antes de procesar— y sigue siendo el correcto para esa
tarea. Éste es el consumo *observado* de una ejecución legítima. Uno acota lo
que se admite; el otro dimensiona cuántas ejecuciones caben a la vez.

## 4. Concurrencia, y qué acota realmente `EJECUCIONES_MAX`

Entrada de 1 000 registros, `EJECUCIONES_MAX` abierto para medir degradación
y no admisión.

| Simultáneas | p50 | p95 | Total | Rendimiento |
|---|---|---|---|---|
| 1 | 1925 ms | 1925 ms | 1,93 s | 0,52 pet/s |
| 2 | 1898 ms | 1903 ms | 1,90 s | 1,05 pet/s |
| 4 | 1990 ms | 2118 ms | 2,13 s | 1,88 pet/s |
| 8 | 2084 ms | 2169 ms | 2,19 s | 3,66 pet/s |
| 16 | 2397 ms | 2670 ms | 2,72 s | 5,89 pet/s |

Con 16 núcleos, 16 ejecuciones simultáneas multiplican el rendimiento por
11 y empeoran el p95 un 39 %. El trabajo del hijo es CPU-bound —parsear un
Excel—, así que **el techo lo ponen los núcleos, no la RAM**: 16 ejecuciones
consumen ~816 MB, nada en una máquina de 96 GB, pero pasado el número de
núcleos subir el cupo sólo reparte los mismos núcleos entre más peticiones.

### Valor calibrado

```
EJECUCIONES_MAX ≈ min( núcleos_lógicos,
                       (RAM_disponible_MB − 512) / 64,
                       32 )
```

- **64 MB por ejecución**: el pico medido de 51 MB, redondeado con margen.
- **512 MB reservados**: el proceso padre (uvicorn más la aplicación).
- **32**: el techo que ya impone el campo, porque por encima el limitador de
  hilos de anyio (40 por defecto) pasaría a ser la concurrencia real en vez
  de este parámetro.

**El valor por defecto pasa de 2 a 4.** El 2 original se justificaba
suponiendo que cada hijo podía llegar al presupuesto de 256 MB de ADR 0021,
o sea 512 MB en total. Con 51 MB medidos, cuatro ejecuciones consumen ~204 MB
—menos de la mitad de lo que aquel valor ya daba por aceptable— y duplican la
capacidad. Es un valor fundado en medición y sigue siendo conservador para
una instancia chica.

**No se sube más porque la instancia no existe.** En esta máquina 16 anda
cómodo, pero elegir 16 sería calibrar contra el servidor de desarrollo. La
fórmula de arriba es lo que hay que aplicar cuando el prerrequisito #0 se
resuelva y se conozcan núcleos y RAM reales.

`TIMEOUT_EJECUCION` se deja en 60 s: contra los 5,3 s del peor caso medido
son más de 10× de margen, y sigue estrictamente por debajo del corte de
2 minutos del portal.

## Lo que sigue abierto

- **La instancia de producción** (prerrequisito #0). Hay que rehacer esta
  corrida ahí y aplicar la fórmula. En un contenedor Linux el costo de
  arranque puede diferir bastante del de Windows.
- **Sólo hay un archivo real**, de 31 registros. Los tamaños grandes de la
  tabla son sintéticos. Si los extractos reales resultan ser mucho mayores,
  la fila de 5 000 registros es la referencia pertinente.
- **La partición de `app/core/errores.py`** descrita en la sección 1: ~0,5 s
  por petición, pendiente de decisión.
