# ADR 0011: Estructura del repositorio en dos paquetes — `core` y `procesadores`

## Estado

Aceptado

## Contexto

El PRD de este servicio establece un invariante central heredado del ADR 0006: el **pipeline común
es agnóstico** y no contiene ninguna referencia — import, condicional o nombre — a un procesador
concreto. El ADR 0006 además advierte de forma explícita que la separación de rutas por procesador
degenera en la alternativa que ese ADR rechazó si una ruta "empieza a validar formatos o a resolver
errores por su cuenta".

Ambos riesgos son de disciplina, no de diseño: aparecen bajo deadline, cuando alguien necesita
resolver rápido una particularidad de un procesador. Una regla escrita en un documento no los
detiene. La estructura de carpetas sí puede: si el límite del invariante coincide con un límite
físico del repositorio, romperlo deja de ser un descuido invisible y pasa a ser una línea visible en
el diff.

Restricciones reales: equipo de una persona, dos toolchains ya en juego (TypeScript y Python,
ADR 0001), y un catálogo de procesadores que va a crecer (3 procesadores reales previstos, más el
fixture del ítem #11).

## Decisión

El repositorio se organiza en **dos paquetes de primer nivel** bajo `app/`:

```
app/
  core/                    # el pipeline agnóstico
    pipeline.py            # los 9 pasos, en orden
    validaciones.py        # cantidad, formato, tamaño, tamaño descomprimido
    errores.py             # los 5 tipos tipificados
    empaquetado.py         # ZIP si hay más de una salida
    temporales.py          # try/finally, limpieza total
    ejecucion.py           # semáforo de admisión + proceso dedicado (ADR 0012)
    db.py                  # espejo de solo lectura de SQL Server
    seguridad.py           # token de servicio
    interfaz.py            # ABC Procesador
  procesadores/            # un paquete autocontenido por procesador
    passthrough/
      modulo.py            # implementa Procesador
      ruta.py              # cáscara fina
    contado_carga/
      modulo.py
      ruta.py
  registry.py              # clave -> instancia
  main.py
```

**Regla verificable que sostiene el invariante: `core/` nunca importa nada de `procesadores/`.**
La dependencia es unidireccional. `procesadores/` conoce a `core/`; `core/` no sabe que
`procesadores/` existe. Se verifica con una comprobación automatizada en CI, no con revisión manual.

Cada procesador es un **paquete autocontenido**: su módulo de negocio y su ruta cáscara viven
juntos, porque son la misma unidad de trabajo y cambian por la misma razón. Dar de alta un
procesador es crear una carpeta, implementar la interfaz, escribir la ruta cáscara y registrarlo —
sin tocar `core/`.

## Alternativas consideradas

- **Tres paquetes: `core` / `rutas` / `procesadores`** — agrupar todas las rutas cáscara en un solo
  paquete permitiría leer la superficie HTTP completa de un vistazo y auditar de un tirón que toda
  ruta delega en el pipeline. Se descartó porque parte cada procesador en dos lugares: agregar uno
  obliga a tocar dos carpetas y a mantener sincronizados dos archivos que solo existen el uno para
  el otro. La auditoría que esa estructura facilita se resuelve mejor con un test automatizado que
  con proximidad física, y ese test se decide igual (ver Consecuencias).

- **Arquitectura hexagonal estricta** (dominio / aplicación / infraestructura, con `Procesador` como
  puerto y FastAPI, SQL Server y el sistema de archivos como adaptadores) — daría máxima
  testabilidad del dominio sin levantar infraestructura, y es una opción legítima dado que el
  pipeline tiene lógica de orquestación real. Se descartó por proporción: el dominio de este
  servicio son nueve pasos secuenciales, y envolverlos en tres capas agrega indirección que un
  equipo de una persona paga en cada lectura sin recuperar en flexibilidad. La costura que la
  arquitectura hexagonal aportaría — poder cambiar de adaptador — ya está cubierta por la interfaz
  `Procesador` del ADR 0006, que es el único punto de extensión que este servicio necesita.

## Consecuencias

- El invariante "el pipeline es agnóstico" pasa de ser una regla recordada a ser una **dependencia
  de paquete verificable**. Una violación no requiere que un revisor la note: falla la comprobación.
- Agregar un procesador toca una sola carpeta nueva más el `registry`. El pipeline permanece
  intacto, que es exactamente el criterio de éxito que el PRD pide medir al incorporar el segundo
  procesador.
- El módulo de negocio y su ruta cáscara están juntos, así que revisar un procesador completo es
  abrir una carpeta.
- **Costo real:** no existe un único lugar donde leer toda la superficie HTTP del servicio. Con el
  catálogo creciendo, saber qué rutas expone el servicio exige recorrer `procesadores/` o consultar
  el registry. Se mitiga con el registry como índice único y con la documentación de rutas que
  genera FastAPI, pero es una pérdida real frente a la alternativa de tres paquetes.
- **Costo real:** la estructura por sí sola impide que `core/` conozca a un procesador, pero **no**
  impide que una ruta cáscara engorde y reimplemente validaciones. Ese segundo riesgo — el que el
  ADR 0006 señala por nombre — sigue necesitando el test de delegación que el PRD exige: cada ruta
  llama al pipeline y no valida por su cuenta. La estructura cubre una mitad del invariante; el test
  cubre la otra.
- La comprobación de dependencia y el test de delegación son ambos infraestructura de CI que hay que
  escribir y mantener. Sin ellos, esta ADR es una convención más.
