# ADR 0016: Health check publico y sin base de datos

## Estado

Aceptado

## Contexto

El PRD exige que toda peticion presente el token de servicio y que sin token valido se rechace con
401, sin excepciones — el criterio de aceptacion lo formaliza asi. La misma seccion pide, para
monitoreo y despliegue, un endpoint de health check. Un probe de orquestador o balanceador no lleva
el token de servicio: si el health esta exento, hay una ruta sin autenticar que ningun documento
declaraba hasta ahora; si no lo esta, el probe siempre recibe 401 y el despliegue nunca queda sano.
Este es el hallazgo H-08 de `REVISION-ADVERSARIAL.md`.

Tampoco estaba decidido si el health consulta SQL Server. Consultarla acopla la liveness del proceso
a la disponibilidad de una dependencia externa; un hipo de base reiniciaria contenedores sanos. No
consultarla deja la pregunta de que exactamente prueba un 200.

## Decision

`GET /salud` es publico y no consulta base de datos. Es la unica ruta sin autenticar del servicio.

La exencion se expresa de forma estructural, no como una lista de excepciones: el token se adjunta
como dependencia unicamente a los routers de procesadores (item #2), nunca como middleware global con
una lista de rutas permitidas. `/salud` no esta "excluido de la autenticacion" — nunca estuvo dentro
de la superficie autenticada. Un allow-list es un error tipografico de distancia de abrir todo el
servicio; este diseno no depende de que nadie lo escriba bien.

`app/salud.py` importa unicamente `fastapi`. Ninguna otra decision de arquitectura hace mas fuerte
esta independencia que el propio grafo de imports.

## Alternativas consideradas

- **Probe configurado con el token de servicio** — mantendria "toda peticion lleva token" sin
  excepciones. Se descarto porque acopla el orquestador a un secreto operativo, y una rotacion del
  token rompe la liveness del despliegue: un reinicio de credencial se convierte en un reinicio en
  bucle de contenedores por un motivo que no tiene nada que ver con si el proceso esta vivo.

- **Readiness probe que consulta SQL Server** — probaria mas que la mera existencia del proceso. Se
  descarto porque un hipo de base reinicia contenedores que estan sanos, y porque duplica el trabajo
  del item #11 (contraste registry contra base de datos), que ya tiene su propio momento de arranque
  para esa verificacion.

- **Sin endpoint de health** — evita la tension por completo. Se descarto porque el despliegue nunca
  podria declararse sano de forma automatica, contradiciendo el requisito explicito del PRD de contar
  con un endpoint para monitoreo.

## Consecuencias

- "Sano" (200 de este probe) y "completamente funcional" (el servicio puede atender una peticion de
  procesamiento) son afirmaciones distintas. Un 200 de `/salud` no prueba que el token sea valido mas
  alla del arranque, que SQL Server sea alcanzable, que el registry y el catalogo de la base de datos
  coincidan, ni que algun procesador pueda ejecutarse.
- Una caida de SQL Server o un desacuerdo entre registry y catalogo no reinicia una instancia sana bajo
  este diseno — ese es el costo aceptado a cambio de que la liveness no dependa de una base de datos.
- Una futura sonda de readiness, si se necesita, tiene su propia ruta y su propio ADR: este documento
  no la anticipa ni la impide.
