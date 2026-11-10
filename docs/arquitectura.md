# Arquitectura

Cotejo es un monolito modular: un proceso Python con FastAPI sirve la API bajo `/api` y los archivos del
frontend construido. La base es PostgreSQL 16 con la extensión `vector`. Un proceso aparte, opcional, expone las
herramientas del asistente por MCP reutilizando los mismos módulos. No hay colas, ni caché externa, ni
servicios separados: con una sola empresa y unos miles de facturas no hacen falta, y así todo se prueba con una
base real y nada más.

```
                 Navegador (React 19 + TanStack Query)
                              |
                         cookie de sesión
                              v
+--------------------- Proceso API (uvicorn, 1 worker) ---------------------+
|  api/   rutas, sesión, roles, errores, cabeceras, límites                 |
|                                                                           |
|  cfdi/        ingesta/        cxp/          documentos/     asistente/    |
|  parser,      carga por       saldos,       extracción,     bucle de      |
|  reglas,      archivo,        antigüedad,   fragmentos,     herramientas -+--> API compatible
|  RFC          duplicados,     tablero,      embeddings,     (lectura +    |    con OpenAI
|               aplicaciones    consultas     búsqueda        proponer)     |
|                                                  propuestas/ (barreras)   |
|  bitacora, seguridad (archivos, cuotas)                                   |
+-------------------------------------|-------------------------------------+
                                      v
                    PostgreSQL 16 + pgvector (vector y texto completo 'spanish')

Proceso MCP (stdio, opcional): mismas herramientas de consulta y la de proponer.
```

## Módulos

| Módulo | Qué hace |
|---|---|
| `cfdi/` | Lee el XML con lxml endurecido, lo convierte en un objeto con `Decimal` y aplica las reglas de rechazo y alerta. |
| `ingesta/` | Procesa cada archivo de una carga en su propia transacción, crea el proveedor por RFC, detecta duplicados y aplica notas de crédito y pagos. |
| `cxp/` | Saldos, antigüedad, tablero y las consultas que usan la API, el asistente y el MCP. |
| `documentos/` | Extrae texto por página, parte en fragmentos, calcula embeddings y hace la búsqueda híbrida. |
| `asistente/` | Bucle propio de llamadas a herramientas, prompt, verificación de cifras y citas. |
| `propuestas/` | Selección de facturas, barreras y aprobación. |
| `seguridad/` | Cookie firmada, contraseñas, subida de archivos, cuotas, cabeceras y CSRF. |
| `semilla/` | Datos ficticios deterministas: genera XML y los pasa por la ingesta real. |
| `api/` | Rutas, dependencias y formato de errores. |

## Flujo de una factura

1. `POST /api/cargas/cfdi` recibe uno o varios archivos. Cada archivo va en su propia transacción: uno malo no
   tumba la carga.
2. Se revisa extensión, tamaño y primeros bytes antes de parsear.
3. Si los bytes traen `<!DOCTYPE` o `<!ENTITY`, se rechaza. Si no, se parsea sin resolver entidades, sin red y
   sin DTD.
4. El parser produce el comprobante leído. Se rechaza si no es CFDI 4.0, no trae timbre o es de nómina o
   traslado.
5. Si el UUID ya existe, el resultado es "ya existía" y no se toca nada. Si no, se crea o reutiliza el
   proveedor por RFC y se guardan factura, conceptos, impuestos y relaciones.
6. Las reglas producen alertas: RFC inválido, total que no cuadra, receptor ajeno, fecha futura, moneda sin tipo
   de cambio, posible duplicado, proveedor en la lista 69-B.
7. Si es nota de crédito o complemento de pago, se aplica a las facturas que relaciona. Si es una factura nueva,
   se le aplican las notas y pagos que estaban esperando su UUID. Un saldo nunca queda negativo.
8. Se escribe la bitácora y se responde por archivo con el resultado y los motivos en español.

## Saldo

Pagos de complementos, notas de crédito y pagos aprobados viven en una sola tabla de aplicaciones. El saldo de
una factura es su total menos la suma de sus aplicaciones, y toda escritura pasa por una sola función que
bloquea la factura. El vencimiento no se guarda: es la fecha de emisión más los días de crédito del proveedor,
así que editar los días de crédito actualiza todo sin migrar datos.

## Flujo de una pregunta al asistente

1. `POST /api/asistente/mensajes`. Se revisa la sesión, la cuota del visitante y la cuota global. Sin llave de
   modelo configurada responde 503 con un mensaje útil.
2. Se arma el prompt de sistema, los últimos turnos y la pregunta, con la lista de herramientas.
3. Hasta 6 llamadas al modelo. Cada llamada a herramienta se valida con Pydantic y ejecuta código propio que
   consulta la base. El modelo no ve ni escribe SQL. El usuario y la fecha salen de la sesión, nunca de los
   argumentos del modelo.
4. Al terminar, el código revisa que cada cifra del texto aparezca en algún resultado de herramienta y que cada
   cita corresponda a un fragmento devuelto en este turno. Lo que no cuadra se marca como advertencia.
5. Se guarda el mensaje con las herramientas usadas, facturas base, citas, advertencias, modelo y tokens. La
   interfaz arma el "cómo lo calculé" con esos datos, no con el texto del modelo.
6. Si el modelo pidió una propuesta, el servicio de propuestas aplica las barreras y la crea en estado
   pendiente. Aprobar es otro endpoint, sin modelo, solo para el rol aprobador.

El texto que viene de facturas y documentos llega al modelo envuelto como dato no confiable, y las barreras no
dependen de lo que diga el modelo.

## Búsqueda

Los PDF se leen página por página con pypdf; TXT y MD cuentan como una página. Un PDF sin texto extraíble queda
marcado y no falla la carga. Los fragmentos miden unos 800 caracteres con traslape de 150 y nunca cruzan de
página, porque la cita es documento y página.

El texto se normaliza en Python (minúsculas, sin acentos salvo la ñ) para que "garantia" encuentre "garantía"
sin extensiones de PostgreSQL. Cada consulta corre dos búsquedas: por vector (multilingual-e5-small, 384
dimensiones, distancia coseno con índice HNSW) y por texto completo con la configuración `spanish`. Las dos
listas se combinan por rango recíproco (RRF, k=60). No hay umbral de similitud: decir "no está en los
documentos" lo decide el prompt y se mide en la evaluación.

## Seguridad

La sesión es una cookie firmada con HMAC-SHA256 (HttpOnly, SameSite=Lax, 8 horas). Toda petición que modifica
exige la cabecera `X-Cotejo: 1`; como no hay CORS, otro sitio no puede mandarla. Las contraseñas de usuarios que
no son de demo usan scrypt. La política de contenido solo permite recursos del mismo origen. Los secretos llegan
solo por variables de entorno y nunca se escriben en registros ni en la bitácora; en producción la app no
arranca sin una `SECRET_KEY` de al menos 32 caracteres.

Los límites de uso cuentan por visitante y por hash de IP, para que borrar la cookie no reinicie la cuota. La IP
sale de `X-Forwarded-For` solo si `CONFIAR_PROXY=1`, y en ese caso se toma la última de la lista, la que agrega
el balanceador.

## Contenedor

Una imagen multietapa: Node construye el frontend, Python instala el backend con uv desde `uv.lock` y descarga el
modelo de embeddings dentro de la imagen. Corre con un usuario sin privilegios y un solo worker, porque el modelo
ocupa cerca de 1 GB por proceso. Al arrancar, `scripts/entrypoint.sh` aplica las migraciones, siembra la demo si
la base está vacía y arranca uvicorn en el puerto de `PORT`.
