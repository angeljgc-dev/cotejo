# API

Con la app corriendo, la referencia completa e interactiva (OpenAPI) está en `/api/docs` y el esquema en
`/api/openapi.json`. Este archivo resume las convenciones y las rutas.

## Convenciones

Todo vive bajo `/api` y habla JSON en UTF-8. Las fechas van en ISO 8601. Los importes viajan como texto decimal
(`"1160.00"`), nunca como número, para no perder centavos en el camino; los de factura van con 2 decimales y
redondeo half-up, los de conceptos tal cual vienen en el XML. Una petición que manda un importe como número
recibe 422.

La sesión es una cookie (`cotejo_sesion`, HttpOnly, 8 horas). Toda petición POST, PATCH o DELETE debe traer la
cabecera `X-Cotejo: 1`; sin ella la respuesta es 403 `CSRF_FALTANTE`. No hay CORS: la API está pensada para el
frontend del mismo origen.

Los errores tienen siempre la misma forma:

```json
{"error": {"codigo": "ROL_INSUFICIENTE", "mensaje": "Esta acción es solo para el rol aprobador.", "detalle": {}}}
```

`detalle` siempre es un objeto. Los códigos comunes son 401 `NO_AUTENTICADO`, 403 `ROL_INSUFICIENTE`, 404
`<ENTIDAD>_NO_ENCONTRADA`, 413 cuando un archivo o la petición pasan del límite, 422 `VALIDACION` (con
`{"campos": [{"campo", "mensaje"}]}`), 429 cuando se agota una cuota (con `{"limite", "se_reinicia"}`) y 500
`ERROR_INTERNO`, que nunca expone detalles internos.

Las listas se paginan con `pagina` (desde 1) y `por_pagina` (1 a 100, 25 por omisión) y responden
`{"elementos": [...], "total", "pagina", "por_pagina"}`.

## Ejemplo con curl

```bash
# Entrar a la demo y guardar la cookie
curl -c cookies.txt -H "X-Cotejo: 1" -H "Content-Type: application/json" \
  -d '{"rol":"capturista"}' http://localhost:8000/api/sesion/demo

# Tablero
curl -b cookies.txt http://localhost:8000/api/tablero

# Subir dos facturas
curl -b cookies.txt -H "X-Cotejo: 1" \
  -F "archivos=@factura1.xml" -F "archivos=@factura2.xml" http://localhost:8000/api/cargas/cfdi
```

## Rutas

| Método y ruta | Rol | Para qué |
|---|---|---|
| `GET /api/salud` | público | Estado de la app y de la base. 503 si la base no responde. |
| `POST /api/sesion/demo` | público | Entrar a la demo como `capturista` o `aprobador`. 404 si la demo no está habilitada. |
| `POST /api/sesion` | público | Entrar con usuario y contraseña. Máximo 5 intentos por minuto por IP. |
| `GET /api/sesion` | cualquiera | Usuario actual. |
| `DELETE /api/sesion` | cualquiera | Salir. |
| `GET /api/configuracion` | cualquiera | Empresa, fecha de hoy, zona horaria, aviso de demo y límites de subida. |
| `POST /api/demo/reiniciar` | cualquiera | Volver a sembrar la demo. Una vez cada 2 minutos. |
| `POST /api/cargas/cfdi` | capturista | Subir hasta 50 XML (2 MB cada uno, 25 MB por petición). Responde un resultado por archivo. |
| `GET /api/facturas` | cualquiera | Lista con filtros por proveedor, tipo, estado, alertas, moneda, fechas y texto. |
| `GET /api/facturas/{id}` | cualquiera | Detalle con conceptos, impuestos, relaciones, aplicaciones y alertas. |
| `GET /api/facturas/{id}/xml` | cualquiera | El XML original. |
| `GET /api/alertas` | cualquiera | Lista de alertas. |
| `POST /api/alertas/{id}/resolver` | aprobador | Resolver una alerta con una nota. No modifica la factura. |
| `GET /api/proveedores` | cualquiera | Lista con adeudo y situación en la lista 69-B. |
| `GET /api/proveedores/{id}` | cualquiera | Detalle con adeudo por moneda y documentos. |
| `PATCH /api/proveedores/{id}` | cualquiera | Cambiar los días de crédito. |
| `GET /api/tablero` | cualquiera | Adeudo total, por proveedor, antigüedad, vencimientos y pendientes. |
| `POST /api/lista-69b` | aprobador | Cargar el CSV de la lista 69-B del SAT. |
| `GET /api/lista-69b/estado` | cualquiera | Si hay lista cargada y cuándo. |
| `GET /api/bitacora` | cualquiera | Quién hizo qué y cuándo, con filtros. |
| `POST /api/documentos` | capturista | Subir PDF, TXT o MD, opcionalmente ligados a un proveedor. |
| `GET /api/documentos` | cualquiera | Lista de documentos. |
| `GET /api/documentos/{id}` | cualquiera | Detalle del documento. |
| `GET /api/fragmentos/{id}` | cualquiera | Un fragmento con su página; es lo que abre una cita. |
| `GET /api/busqueda` | cualquiera | Búsqueda híbrida en los documentos. |
| `GET /api/asistente/estado` | cualquiera | Si el asistente está disponible y cuántas preguntas quedan hoy. |
| `GET /api/asistente/conversacion` | cualquiera | La conversación más reciente del usuario, o `null`. |
| `POST /api/asistente/conversaciones` | cualquiera | Abrir una conversación. |
| `GET /api/asistente/conversaciones/{id}` | cualquiera | Mensajes de una conversación propia. |
| `POST /api/asistente/mensajes` | cualquiera | Preguntar. La respuesta trae herramientas usadas, facturas base, citas y advertencias. |
| `POST /api/propuestas` | capturista | Crear una propuesta de pago con presupuesto y horizonte o fecha límite; opcionalmente, una lista de facturas. |
| `GET /api/propuestas` | cualquiera | Lista de propuestas. |
| `GET /api/propuestas/{id}` | cualquiera | Detalle con renglones, excluidas y si el usuario puede decidir. |
| `POST /api/propuestas/{id}/aprobar` | aprobador | Aprobar: registra los pagos en una sola transacción. |
| `POST /api/propuestas/{id}/rechazar` | aprobador | Rechazar con un motivo. |

Quien creó una propuesta no puede aprobarla ni rechazarla (403 `MISMO_USUARIO`). Al aprobar se revalida cada
renglón contra el estado actual; si alguno ya no pasa las barreras, responde 409 `RENGLONES_INVALIDOS` y no se
aplica nada.

## Servidor MCP

`python -m cotejo.mcp_servidor` arranca un servidor MCP por stdio con las mismas herramientas de consulta del
asistente y la de proponer pagos. No tiene ninguna que apruebe o pague. Actúa como el usuario de `MCP_USUARIO`.
