# Despliegue

Cotejo se publica como una sola imagen de contenedor. La misma imagen sirve en cualquier hospedaje: se configura
con variables de entorno y escucha en el puerto que diga `PORT` (8000 si no está definida). Necesita una base
PostgreSQL 16 con la extensión `vector`.

Al arrancar, el contenedor aplica las migraciones, siembra la demo si la base está vacía y
`SEMBRAR_SI_VACIA=1`, y arranca uvicorn con un solo worker.

## Memoria

El modelo de embeddings (multilingual-e5-small) ocupa cerca de 1 GB de memoria por proceso. Pide al menos 2 GB
para el contenedor. Los planes gratuitos de 512 MB no alcanzan para la búsqueda por significado; ver el plan C.

## Variables para producción

| Variable | Valor | Por qué |
|---|---|---|
| `DATABASE_URL` | URL de la base, con `sslmode=require` si el proveedor lo pide | Acepta `postgres://` y `postgresql://`. |
| `SECRET_KEY` | 32 caracteres o más, aleatoria | Firma la cookie. Sin ella la app no arranca. |
| `COOKIE_SEGURA` | `1` | El hospedaje sirve por HTTPS. |
| `CONFIAR_PROXY` | `1` | La IP del visitante llega en `X-Forwarded-For`; sin esto, todos comparten la misma cuota. |
| `DEMO_HABILITADA` | `1` para la demo pública | Entrar con un clic. |
| `SEMBRAR_SI_VACIA` | `1` para la demo pública | Datos ficticios en el primer arranque. |
| `LLM_API_KEY` | llave del proveedor del modelo | Opcional. Sin ella el chat se desactiva con aviso. |
| `CHAT_LIMITE_GLOBAL_DIA` | según la cuota real de tu llave | El valor por omisión (60) es un techo conservador. |

El resto de las variables, con su explicación, están en `.env.example`. Para generar la clave:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`CLAVE_TEMPORAL_SI_FALTA=1` existe solo para `docker compose` en local: genera una clave al arrancar si falta.
No la uses en un hospedaje real.

## Opción recomendada: Cloud Run con Neon

Costo esperado: cero dentro de las capas gratuitas. Cloud Run da cada mes 180,000 vCPU-segundo, 360,000
GiB-segundo y 2 millones de solicitudes (https://docs.cloud.google.com/free/docs/free-cloud-features). Neon Free
incluye pgvector y no pide tarjeta (https://neon.com/pricing). Cloud Run sí pide una cuenta de facturación con
tarjeta.

### 1. Base en Neon

1. Crea un proyecto en Neon con PostgreSQL 16.
2. Copia la cadena de conexión de la rama principal. Se ve así:
   `postgresql://usuario:contrasena@ep-algo-123456.us-east-2.aws.neon.tech/neondb?sslmode=require`
3. No hace falta crear la extensión a mano: la primera migración corre `CREATE EXTENSION IF NOT EXISTS vector`.

Neon suspende la base tras 5 minutos sin uso. La primera petición después de eso tarda más.

### 2. Proyecto de Google Cloud

```bash
gcloud auth login
gcloud config set project TU_PROYECTO
gcloud config set run/region us-central1
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
```

Antes de seguir, crea en la consola de facturación una alerta de presupuesto de 1 USD.

### 3. Secretos

```bash
printf '%s' "postgresql://...neon.tech/neondb?sslmode=require" | gcloud secrets create cotejo-database-url --data-file=-
python -c "import secrets; print(secrets.token_urlsafe(48), end='')" | gcloud secrets create cotejo-secret-key --data-file=-
printf '%s' "tu_llave_del_modelo" | gcloud secrets create cotejo-llm-api-key --data-file=-
```

La cuenta de servicio con la que corre Cloud Run necesita el rol `roles/secretmanager.secretAccessor` sobre esos
secretos.

### 4. Desplegar

Desde la raíz del repositorio. `--source .` construye con el `Dockerfile` en Cloud Build y sube la imagen a
Artifact Registry:

```bash
gcloud run deploy cotejo \
  --source . \
  --memory 2Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --concurrency 20 \
  --timeout 60 \
  --allow-unauthenticated \
  --set-env-vars "COOKIE_SEGURA=1,CONFIAR_PROXY=1,DEMO_HABILITADA=1,SEMBRAR_SI_VACIA=1" \
  --set-secrets "DATABASE_URL=cotejo-database-url:latest,SECRET_KEY=cotejo-secret-key:latest,LLM_API_KEY=cotejo-llm-api-key:latest"
```

Cloud Run define `PORT` (8080) y la imagen lo respeta. `--max-instances 1` evita que la demo se multiplique y
gaste cuota; además los límites de uso viven en la base, así que funcionan igual con una o varias instancias.

### 5. Comprobar

```bash
URL="$(gcloud run services describe cotejo --format 'value(status.url)')"
bash .github/scripts/humo.sh "$URL"
```

Es la misma prueba de humo que corre en CI: salud, frontend, entrar a la demo y tablero con datos.

### Reiniciar la demo cada noche

La demo es compartida: todos los visitantes ven los mismos datos. Al arrancar, el contenedor solo siembra si la
base está vacía, así que apagarse por inactividad no borra nada. Para dejarla limpia, el botón "Reiniciar demo"
de la interfaz vuelve a sembrar (una vez cada 2 minutos como máximo). Lo mismo se puede programar cada noche
desde cualquier tarea programada, con dos llamadas:

```bash
curl -fsS -c /tmp/cookies -H "X-Cotejo: 1" -H "Content-Type: application/json" \
  -d '{"rol":"capturista"}' "$URL/api/sesion/demo"
curl -fsS -b /tmp/cookies -H "X-Cotejo: 1" -H "Content-Type: application/json" \
  -d '{}' "$URL/api/demo/reiniciar"
```

### Arranque en frío

Con `min-instances=0`, la primera visita después de un rato sin tráfico espera a que arranque el contenedor (la
imagen pesa más de 1 GB por el modelo) y a que Neon despierte. No lo he medido; estimo entre 10 y 20 segundos.

## Plan B: Hugging Face Docker Space

Requiere plan PRO (9 USD al mes, https://huggingface.co/pricing): con cuenta personal gratuita no se pueden
crear Docker Spaces (https://huggingface.co/docs/hub/spaces-overview). Da 16 GB de memoria. La base puede seguir
en Neon. Variables extra: `PORT=7860` (el puerto por omisión de los Spaces) y
`FRAME_ANCESTORS=https://huggingface.co`, porque el Space muestra la app dentro de un iframe. Los secretos van en
la configuración del Space.

## Plan C: Render Free

No pide tarjeta (https://render.com/docs/free). Se duerme a los 15 minutos sin tráfico y tarda alrededor de un
minuto en despertar. La página no publica la memoria del plan gratuito; si es de 512 MB, el modelo no cabe. En
ese caso usa `BUSQUEDA_MODO=texto`: la búsqueda queda solo por palabras exactas y la demo lo avisa. La base va
en Neon (el PostgreSQL gratuito de Render expira a los 30 días).

## Cualquier otro hospedaje

Lo que la imagen necesita: una URL de PostgreSQL 16 con `vector`, `SECRET_KEY`, 2 GB de memoria y que el
hospedaje mande el tráfico al puerto de `PORT`. La ruta `GET /api/salud` responde 200 cuando la app y la base
están bien, y 503 si la base no responde; úsala como sonda de salud.
