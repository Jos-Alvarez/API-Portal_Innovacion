# ADR 0013: Lectura directa del contrato en SQL Server, sin cache

## Estado

Aceptado

## Contexto

El ADR 0005 establece que el servicio accede a SQL Server en **solo lectura estructural**: sus
modelos Python son un espejo del esquema que dicta Prisma en el portal, con un usuario de base de
datos acotado a `SELECT`, sin DDL y sin escritura. El ADR 0006 hace de la fila `procesador`
(`entradas_min`, `entradas_max`, `tamano_max`, `tamano_max_total`, `salida_esperada`) la **única
fuente de verdad del contrato** de entrada/salida, y el paso 1 del pipeline la resuelve en cada
ejecución.

Eso pone la base de datos en el camino crítico de toda petición. El PRD lista "la base de datos no
responde" como caso borde sin respuesta, y quedaba abierto si conviene cachear la fila para reducir
consultas y tolerar cortes.

Un dato desactiva buena parte del argumento a favor de la cache: **si SQL Server está caído, el
portal falla antes que este servicio**. El ADR 0006 establece que el portal verifica la asignación
del usuario en SQL Server *antes* de reenviar los archivos. Una petición no puede llegar acá con la
base inaccesible, salvo en la ventana entre ambas consultas. Cachear para sobrevivir a ese escenario
protege contra algo que, en la práctica, no ocurre de forma aislada.

## Decisión

El pipeline **lee la fila `procesador` directamente en cada ejecución**, con un `SELECT`
parametrizado por `clave_procesador`, sin cache de ningún tipo.

- **La lectura ocurre en el proceso padre**, en el paso 1 del pipeline, antes de despachar el
  trabajo al proceso dedicado del ADR 0012. **Los procesos hijo nunca tocan la base de datos**: no
  heredan conexiones ni las abren. La superficie de acceso a datos queda confinada a la capa web.
  El arranque forzado en `spawn` que fija el ADR 0012 es lo que hace estructural la primera mitad de
  esa regla: el hijo arranca con un intérprete limpio y no hereda los descriptores del pool de
  `pyodbc` del padre.
- El espejo se implementa con **SQLAlchemy Core** sobre el driver `pyodbc`: definiciones de tabla
  declarativas que documentan el espejo y sirven de punto único de actualización cuando Prisma
  migra, consultas parametrizadas, y pool de conexiones en el worker de API. **Sin ORM ni sesiones**:
  no hay entidades que mapear ni unidad de trabajo que gestionar, porque no se escribe nada.
- Si la base no responde, se devuelve un **error tipificado** de servicio no disponible, nunca un
  stack trace.
- La fila se lee filtrando por procesador **activo**; una fila inexistente o inactiva produce el
  error tipificado de clave inexistente.

## Alternativas consideradas

- **Cache en memoria con TTL corto y respaldo a la última copia buena** — reduciría las consultas y
  toleraría un corte breve de base. Se descartó por dos razones. La primera es de corrección: durante
  el TTL el servicio trabaja con un contrato viejo, de modo que bajar un `tamano_max` o desactivar un
  procesador desde el panel admin del portal (ítem #6) no rige de inmediato, y con varios workers
  cada proceso mantiene su propia copia con vencimientos desfasados — el comportamiento del sistema
  pasa a depender de qué worker atendió la petición. La segunda es que el beneficio de resiliencia
  es en gran medida ilusorio, por el motivo explicado en el Contexto.

- **Cache con invalidación explícita desde el portal** (endpoint que el portal invoca al editar una
  fila) — daría frescura y resiliencia a la vez. Se descartó porque agrega superficie HTTP nueva que
  hay que autenticar y mantener, y porque introduce un acoplamiento **portal → servicio en sentido
  inverso** al que fijaron los ADR 0005 y 0006, donde el portal es dueño y escribe y el servicio solo
  lee. Además un aviso perdido deja la cache vieja de forma silenciosa e indefinida, y con varios
  workers habría que invalidar en todos.

## Consecuencias

- **Cero desincronización con el panel de administración.** Lo que un admin cambia en la fila rige en
  la petición siguiente. El comportamiento del servicio es una función directa del estado de la base,
  sin estado intermedio que razonar ni que depurar.
- No hay código de cache, invalidación ni vencimiento que escribir, testear ni mantener. Para un
  equipo de una persona, eso es tiempo que va a la lógica que importa.
- El acceso a datos queda confinado al proceso padre, lo que refuerza el aislamiento del ADR 0012.
  Que un módulo de negocio no alcance la base **no es gratis**: lo sostienen tres cosas concretas y
  ninguna es la buena voluntad de quien escribe el módulo — el arranque en `spawn`, que impide
  heredar conexiones; la comprobación estática de imports que prohíbe a `procesadores/` importar
  `core.db` (Technical Design, "Invariantes de arquitectura"); y el usuario de base de datos acotado
  a `SELECT`, que limita el daño si las dos anteriores fallaran.
- **Costo real:** la base de datos queda en el camino crítico de **cada** ejecución. Una instancia
  lenta o saturada suma latencia a todas las peticiones y consume presupuesto del p95 de 15 segundos.
  Es una consulta por clave primaria, pero el acoplamiento existe y hay que vigilarlo si la latencia
  se degrada.
- **Costo real:** el servicio no tolera ningún corte de base, ni siquiera de segundos. Se acepta
  porque el portal comparte esa dependencia y falla primero, pero significa que la disponibilidad de
  este servicio nunca puede ser mejor que la de SQL Server.
- Mantener el espejo de SQLAlchemy al día tras cada migración de Prisma es trabajo manual recurrente
  (ya señalado como costo residual en el ADR 0005). Un desajuste se manifiesta como error de lectura
  en tiempo de ejecución, no en el arranque, salvo que se agregue una verificación explícita al
  iniciar.
