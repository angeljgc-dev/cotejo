# Decisiones

Registro corto de las decisiones de diseño, con su contexto y lo que cuestan. Cuando una regla no viene de una
fuente oficial lo digo: "regla propia". Las fuentes se consultaron el 9 de noviembre de 2026.

## ADR-a: regla del total del CFDI 4.0

Contexto: el sistema debe avisar cuando el total de una factura no cuadra.

Decisión: la fórmula es la oficial de la Guía de llenado del Anexo 20 (p. 10) y de la documentación del
atributo `Total` en `cfdv40.xsd`: subtotal, menos descuentos, más impuestos trasladados (federales y locales),
menos impuestos retenidos. Los impuestos locales salen del complemento `implocal` (atributos
`TotaldeTraslados` y `TotaldeRetenciones`). La tolerancia de 0.01 para monedas de 2 decimales es regla propia,
derivada de las preguntas 37 y 39 de la guía sobre redondeo.

Consecuencia: no hay alertas falsas por redondeo. No se replican los límites por concepto que valida el PAC.

Fuentes:
- http://omawww.sat.gob.mx/tramitesyservicios/Paginas/documentos/Anexo_20_Guia_de_llenado_CFDI.pdf
- http://www.sat.gob.mx/sitio_internet/cfd/4/cfdv40.xsd
- http://www.sat.gob.mx/sitio_internet/cfd/implocal/implocal.xsd

## ADR-b: dígito verificador del RFC

Contexto: no encontré un documento oficial público con el algoritmo. El formato sí es oficial: el patrón
`t_RFC` de `tdCFDI.xsd` del SAT, que termina en `[0-9A]`, coherente con un módulo 11.

Decisión: uso el algoritmo que implementa la librería python-stdnum (`stdnum/mx/rfc.py`), que cita un documento
del SAT entregado por transparencia en 2005; esa liga ya no sirve. Alfabeto
`0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ Ñ`, los 12 caracteres previos rellenados con espacios a la izquierda,
suma de `índice * (13 - posición)` y dígito `alfabeto[(11 - suma) % 11]`. El RFC genérico `XAXX010101000` queda
como excepción.

Consecuencia: como no hay fuente primaria, un RFC que no cumple genera una alerta, nunca un rechazo. La misma
librería advierte que cerca de 1.5% de los RFC en uso no cumplen el dígito. En las pruebas, python-stdnum sirve
de oráculo con pruebas de propiedades; no se distribuye con la app.

Fuentes:
- http://www.sat.gob.mx/sitio_internet/cfd/tipoDatos/tdCFDI/tdCFDI.xsd
- https://github.com/arthurdejong/python-stdnum

## ADR-c: no validar contra XSD en tiempo de ejecución

Contexto: `cfdv40.xsd` importa `catCFDI.xsd` (6 MB, unas 162 mil enumeraciones). Medí compilarlo: 0.20 s y
116 MB más de RAM.

Decisión: reglas explícitas en código para rechazos y alertas, y los XSD oficiales solo en las pruebas, para
garantizar que los XML ficticios son CFDI válidos.

Por qué: el nodo `Addenda` acepta cualquier contenido, pero en modo estricto una addenda sin su esquema haría
fallar facturas válidas; los catálogos cambian (un código postal nuevo daría rechazos falsos) y la memoria es
escasa en el hospedaje. Costo: no detecto claves de catálogo inválidas; el PAC ya las validó al timbrar.

## ADR-d: proveedor del modelo de lenguaje

Contexto: la demo es pública y gratuita, así que el modelo debe tener plan gratuito y soporte de herramientas.

Hallazgos en las páginas oficiales:
- Groq: todos sus modelos aceptan herramientas, incluido `openai/gpt-oss-120b`; los gpt-oss no hacen llamadas
  en paralelo. La tabla publicada de límites es la del plan Developer (30 por minuto, 1,000 al día, 8 mil tokens
  por minuto). https://console.groq.com/docs/tool-use, https://console.groq.com/docs/rate-limits
- Gemini: compatibilidad con la API de OpenAI documentada, con herramientas; las cuotas gratuitas solo se ven en
  AI Studio. https://aistudio.google.com/docs/openai
- OpenRouter con modelos `:free`: 20 por minuto y 50 al día sin créditos comprados.
  https://openrouter.ai/docs/api/reference/limits

Decisión: Groq con `openai/gpt-oss-120b` por omisión; Gemini y OpenRouter como alternativas. Cambiar de
proveedor es configurar `LLM_BASE_URL`, `LLM_MODELO` y `LLM_API_KEY`.

Consecuencia: la cuota gratuita es baja, por eso hay límites diarios por visitante y global, y la evaluación pausa
entre llamadas y puede reanudarse.

## ADR-e: parser propio en lugar de satcfdi

Contexto: `satcfdi` sirve para generar, firmar y renderizar CFDI, y trae como dependencias obligatorias
weasyprint, cryptography, pyOpenSSL y otras; weasyprint necesita bibliotecas nativas en Windows.

Decisión: un parser propio sobre lxml que lee solo los nodos que uso. Tampoco uso defusedxml (sin versiones
nuevas desde 2021): rechazar DTD y entidades antes de parsear y las opciones de lxml cubren XXE y bombas de
expansión, y hay pruebas para cada ataque.

Fuente: https://pypi.org/project/satcfdi/, https://pypi.org/project/defusedxml/

## ADR-f: modelo de embeddings

Decisión: `intfloat/multilingual-e5-small` en fp32 con fastembed (ONNX en CPU, sin PyTorch). 384 dimensiones y
hasta 512 tokens. En mis pruebas con preguntas en español encontró el fragmento correcto en 6 de 6 casos;
paraphrase-multilingual-MiniLM acertó 5 de 6 y corta a 128 tokens.

Costo: medí 939 MB de memoria en un hilo (601 MB la variante int8). Ningún modelo multilingüe con vocabulario
grande cabe en 512 MB, así que la memoria se resuelve eligiendo hospedaje y no bajando calidad. La variante int8
queda configurable si la evaluación del buscador no empeora.

Fuente: https://huggingface.co/intfloat/multilingual-e5-small, https://github.com/qdrant/fastembed

## ADR-g: una tabla de aplicaciones para el saldo

Decisión: pagos de complemento, notas de crédito y pagos aprobados viven en una tabla `aplicaciones`, y toda
escritura pasa por una función que bloquea la factura. Alternativa descartada: tablas separadas sumadas en
vistas; serían tres lugares donde romper la regla de que el saldo nunca es negativo.

## ADR-h: vencimiento calculado, no guardado

Decisión: `fecha_emision + dias_credito` en la consulta. Editar los días de crédito de un proveedor actualiza
todo sin migrar datos. Costo: un join más en el tablero, irrelevante con 2,000 facturas.

## ADR-i: la propuesta la arma el código

Decisión: el modelo pide la propuesta (presupuesto y horizonte, o facturas concretas) y el código elige las
facturas y aplica las barreras. La propuesta es reproducible, se puede evaluar por el estado de la base y no
depende de que el modelo sume bien. La selección es voraz por vencimiento y saldo: regla propia.

## ADR-j: normalización propia en lugar de unaccent

Decisión: el texto normalizado se calcula en Python y el índice de texto completo se arma sobre él. Mismo efecto
que `unaccent`, sin extensiones, y el mismo comportamiento en desarrollo local, CI y producción, porque el
PostgreSQL local de desarrollo no trae extensiones extra.

## ADR-k: cookie firmada y CSRF por cabecera

Decisión: sesión en una cookie firmada con HMAC de la biblioteca estándar, sin tabla de sesiones ni
dependencias. Toda petición que modifica exige `X-Cotejo: 1`. Costo: no se puede cerrar una sesión concreta
antes de que expire a las 8 horas; aceptable para este alcance.

## ADR-l: chat síncrono

Decisión: una petición, una respuesta, sin streaming. Es más simple de probar y de calificar. Costo: la persona
ve un indicador de carga que puede durar unos 20 segundos.

## ADR-m: hospedaje de la demo

Contexto: la demo necesita unos 2 GB de memoria por el modelo de embeddings. Hugging Face pide plan PRO para
crear Docker Spaces con cuenta personal (https://huggingface.co/docs/hub/spaces-overview), y los planes
gratuitos de 512 MB no alcanzan.

Decisión: una sola imagen que sirve en cualquier hospedaje de contenedores, configurada por variables de entorno
y con el puerto en `PORT`. La opción recomendada es Cloud Run con Neon como base; las alternativas y sus costos
están en [despliegue.md](despliegue.md).
