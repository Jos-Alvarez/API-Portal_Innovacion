# ADR 0017: Token de servicio en `Authorization: Bearer`

## Estado

Aceptado

## Contexto

El PRD exige un token de servicio obligatorio "en los headers", con un 401 "sin pistas" cuando el
token falta, está vacío, está malformado o es incorrecto. No nombra un header concreto ni un
esquema, así que esa decisión queda abierta hasta este cambio (ítem #2 del backlog).

ADR 0014 define un vocabulario cerrado de errores tipificados (`formato`/`tamano`/`contenido`/
`cantidad`/`clave_inexistente`) para las respuestas de error del servicio. El 401 de autenticación
no encaja en ese vocabulario -- no es un error sobre el contenido de una petición ya autenticada,
es el rechazo previo a considerar esa petición. Sin una decisión escrita, la tentación natural
cuando el ítem #3 defina el contrato de error tipificado será "completar el trabajo" y darle al 401
un cuerpo con esa misma forma, borrando una frontera que hoy es intencional.

## Decisión

El token de servicio viaja en la cabecera estándar `Authorization`, con el esquema `Bearer`:
`Authorization: Bearer <token>`.

Todo rechazo -- ausencia de cabecera, esquema incorrecto, falta de espacio tras el esquema,
credencial vacía, espacios irregulares, credencial no-ASCII, cabeceras `Authorization` duplicadas o
un token bien formado pero incorrecto -- produce la misma respuesta: **401 con cuerpo vacío** y la
cabecera `WWW-Authenticate: Bearer`.

El 401 queda **explícitamente fuera** del enum cerrado de ADR 0014 y **nunca** debe adquirir un
cuerpo tipificado con esa forma.

## Alternativas consideradas

- **Cabecera propia, p. ej. `X-Token-Servicio`** -- se descartó porque los proxies, balanceadores y
  stacks de logging redactan `Authorization` por defecto, y no van a redactar un nombre inventado.
  Usar el header estándar es lo que hace que el token no aparezca en logs de infraestructura sin
  tener que confiar en que cada capa intermedia conozca el nombre nuevo.

- **Cuerpo de error con la forma de ADR 0014** (`{"tipo": ..., "contexto": ...}`) -- se descartó
  porque el enum de ADR 0014 es cerrado y cualquier cuerpo es superficie de fuga que el PRD prohíbe
  explícitamente ("sin pistas"). Un cuerpo tipificado, aunque genérico, ya es una pista.

- **Omitir `WWW-Authenticate`** -- se descartó porque RFC 7235 indica que una respuesta 401 SHOULD
  incluirla, y esta cabecera solo nombra el esquema (`Bearer`), que este mismo ADR ya hace público.
  Omitirla no agrega secreto y rompe la conformidad HTTP sin necesidad.

## Consecuencias

- El futuro cliente del portal (ítem #10) debe enviar exactamente `Authorization: Bearer <token>`.
- El ítem #3, al definir el contrato de error tipificado, debe tratar el 401 como un caso especial
  fuera de su enum -- este ADR es la referencia que documenta esa frontera.
- Un cuerpo vacío significa que ningún cliente puede distinguir, desde la respuesta, cuál de las
  variantes de rechazo ocurrió. Esa indistinguibilidad es el punto: es lo que impide que un tercero
  use la respuesta para tantear cuál pieza del header está mal.
