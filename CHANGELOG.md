# Cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones siguen
[SemVer](https://semver.org/lang/es/).

## [0.1.0] - 2026-11-09

Primera versión.

### Agregado

- Carga de CFDI 4.0 en XML con resultado por archivo: aceptada, aceptada con alertas, rechazada o ya existía.
- Rechazos por XML mal formado, versión distinta de 4.0, falta de timbre y comprobantes de nómina o traslado.
- Alertas por RFC inválido, total que no cuadra, receptor ajeno, fecha futura, moneda sin tipo de cambio,
  posible duplicado y proveedor en la lista 69-B.
- Protección contra XXE, DTD y bombas de expansión en el XML.
- Notas de crédito y complementos de pago aplicados al saldo, con parcialidades.
- Saldos, antigüedad en cinco grupos y tablero de cuentas por pagar, con importes exactos en `Decimal`.
- Documentos PDF, TXT y MD con búsqueda híbrida (pgvector y texto completo) y citas por documento y página.
- Asistente con herramientas de consulta que responde con las cifras de la base y cita sus fuentes.
- Propuestas de pago creadas por código con barreras, y aprobación solo por el rol aprobador.
- Bitácora de cargas, propuestas, aprobaciones y rechazos.
- Servidor MCP con las herramientas de consulta y la de proponer.
- Interfaz en React con siete vistas, usable en teléfono y con teclado.
- Modo demo con datos ficticios deterministas y botón para reiniciarla.
- Imagen de contenedor, `docker-compose.yml` y CI en GitHub Actions con prueba de humo, e2e y gitleaks.
- Evaluación del buscador y del asistente con el modelo real.
