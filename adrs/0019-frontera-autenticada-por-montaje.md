# ADR 0019: Frontera autenticada por montaje

## Estado

Aceptado

## Contexto

El PRD exige "401 antes de leer el cuerpo del request". ADR 0016 nombra el mecanismo de autenticación
vigente: el token se adjunta como dependencia únicamente a los routers de procesadores
(`Depends(exigir_token)`), nunca como middleware global con una lista de rutas permitidas -- un
allow-list es, en palabras de ese ADR, "un error tipográfico de distancia de abrir todo el servicio".

Ese mecanismo no puede cumplir el requisito del PRD. FastAPI lee el cuerpo completo de la petición
--incluido un multipart de varios megabytes-- antes de resolver una sola dependencia, tanto a nivel de
ruta como de router (`fastapi/routing.py:425-450`, `:752-755`). Un `Depends(exigir_token)`, sin
importar dónde se lo declare, rechaza **después** de que el cuerpo ya fue leído completo. Una carga sin
token válido se procesaría entera en memoria o disco antes de que el token se mirara.

Los dos mecanismos alternativos obvios también se descartan:

- **Middleware global de la app + lista de rutas permitidas.** ADR 0016 lo prohíbe en el propio texto:
  reintroduce exactamente el allow-list que ese ADR evita a propósito.
- **Sub-aplicación `FastAPI` anidada, con la autenticación en su `Mount(middleware=...)`.** La
  sub-app instala su propio `ExceptionMiddleware`, que sobrescribe la tabla de manejadores de
  excepción para todo lo que vive dentro de ella (`starlette/middleware/exceptions.py:47-63`). Los
  tres manejadores del ítem #2 y del ítem #6 tendrían que registrarse dos veces, en dos lugares, para
  siempre -- y la sub-app crea su propio conjunto de rutas de documentación (`/interno/docs`, etc.).

## Decisión

La superficie autenticada es el montaje `/interno` (prefijo tomado de `PRD.md:76-77`, no inventado
aquí): `Mount("/interno", app=router_interno, middleware=[Middleware(AutenticacionDeBorde)])`, donde
`router_interno` es un `APIRouter` sin envolver -- no una `FastAPI` anidada.

`AutenticacionDeBorde` es un middleware ASGI puro que decide leyendo únicamente `scope["headers"]` a
través de `Request(scope)` y llama a `exigir_token` -- el mismo, único, sitio de `raise` del ítem #2.
Nunca llama a `receive()`, así que nunca hay oportunidad de leer un byte del cuerpo antes del rechazo:
el `Request` que construye recibe el `receive` vacío por defecto de Starlette, que lanza si algo
intenta usarlo, de modo que la imposibilidad de leer el cuerpo es estructural, no una convención que un
futuro cambio pueda romper por descuido.

El rechazo (`TokenInvalido`) se propaga como excepción y sale de la petición sin que este módulo
construya ninguna respuesta. El `Mount` vive dentro del enrutamiento de la app exterior, y el
`ExceptionMiddleware` de esa misma app exterior envuelve al `Router` completo, montajes incluidos
(`starlette/middleware/exceptions.py:47-63`). La excepción se despacha por `type(exc).__mro__`
(`starlette/_exception_handler.py:16-20`), llega al manejador ya registrado por el ítem #2 y produce el
401 de ADR 0017 -- cuerpo vacío, `WWW-Authenticate: Bearer` -- sin que exista un segundo sitio de
construcción de esa respuesta en ningún lugar del repositorio.

`/salud` y las cuatro rutas de documentación de FastAPI (`/openapi.json`, `/docs`,
`/docs/oauth2-redirect`, `/redoc`) permanecen en la app exterior, fuera del montaje. No están
"excluidas" de la autenticación por ninguna lista: nunca estuvieron dentro de la superficie
autenticada, la misma formulación estructural que usa ADR 0016. **ADR 0016 no se revierte**: su
invariante -- ninguna lista de rutas permitidas en ningún lugar -- se mantiene intacto. Solo se
sustituye el mecanismo que ese ADR nombraba (`Depends` en routers de procesadores) por uno que sí
puede rechazar antes de leer el cuerpo.

## Alternativas consideradas

- **`Depends(exigir_token)` en los routers de procesadores (mecanismo nombrado por ADR 0016).**
  Descartado: no puede rechazar antes de leer el cuerpo -- FastAPI ya lo leyó para cuando la primera
  dependencia se resuelve. Es precisamente el mecanismo que este ADR sustituye.

- **Middleware global de la app + lista de rutas permitidas.** Descartado: ADR 0016 lo prohíbe de
  forma explícita, por el mismo motivo que sigue vigente -- un allow-list es un error tipográfico de
  distancia de abrir todo el servicio, y este diseño no debe depender de que nadie lo escriba bien.

- **Sub-aplicación `FastAPI` anidada, autenticación en su propio `Mount(middleware=...)`.**
  Descartado: su `ExceptionMiddleware` propio sobrescribe la tabla de manejadores para todo lo que
  vive dentro de la sub-app, duplicando el registro de los tres manejadores existentes en dos lugares
  distintos y agregando un segundo conjunto de rutas de documentación que nadie pidió.

## Consecuencias

- Toda ruta de procesador debe vivir dentro de `/interno`. Una ruta registrada fuera de ese montaje
  queda, por construcción, sin autenticar -- este es el nuevo modo de fallo que reemplaza al anterior
  ("alguien olvidó `dependencies=[Depends(exigir_token)]` en un router nuevo", que nada detectaba). El
  pin de conjunto de rutas (`tests/test_seguridad_token.py::test_rutas_de_produccion_no_cambian`) es el
  detector: desciende ahora también dentro de `Mount`, así que una ruta fuera del montaje enrojece el
  conjunto de rutas públicas, y una ruta dentro del montaje aparece en el conjunto de montajes
  esperado, con el prefijo `/interno`.
- Las rutas dentro de `/interno` son invisibles para el esquema `/openapi.json` de la app exterior: los
  recorredores de rutas de FastAPI descienden en `_IncludedRouter` pero nunca en `Mount`
  (`fastapi/routing.py:1842-1850`, `:1828-1839`; `fastapi/openapi/utils.py:558`, `:628`). Ningún
  cliente consume ese esquema hoy; se acepta el costo y se revisita si eso cambia.
- El montaje se crea vacío en este cambio -- cero rutas de procesador. Queda probado por sí mismo: sin
  token, `GET /interno/lo-que-sea` responde 401 (el middleware corrió); con el token correcto, 404 (el
  middleware dejó pasar y el router vacío no encontró nada). El primer caso real que se monte dentro de
  `router_interno` -- un `APIRoute` dentro de un `APIRouter` sin envolver, montado con `Mount` -- queda
  sin ejercitar por este cambio; el medio de reunión temporal que lo agregue debe verificarlo.
