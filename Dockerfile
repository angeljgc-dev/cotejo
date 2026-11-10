# syntax=docker/dockerfile:1

# Imagen única de Cotejo: API, frontend construido y modelo de embeddings.
# Sirve igual en cualquier hospedaje de contenedores; todo se configura con variables de entorno.

ARG PYTHON_IMAGEN=python:3.11.18-slim-trixie
ARG NODE_IMAGEN=node:24.22.2-trixie-slim
ARG UV_IMAGEN=ghcr.io/astral-sh/uv:0.13.7

FROM ${UV_IMAGEN} AS uv

# Etapa 1: frontend
FROM ${NODE_IMAGEN} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# Etapa 2: backend
FROM ${PYTHON_IMAGEN} AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:${PATH}" \
    HF_HOME=/opt/modelos \
    STATIC_DIR=/app/static \
    PORT=8000

RUN groupadd --system --gid 10001 cotejo \
    && useradd --system --uid 10001 --gid cotejo --home-dir /app --no-create-home --shell /usr/sbin/nologin cotejo

WORKDIR /app

# Primero solo las dependencias: esta capa se reutiliza mientras uv.lock no cambie.
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY pyproject.toml uv.lock alembic.ini ./
COPY src/ ./src/
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# El modelo queda dentro de la imagen para no descargarlo en cada arranque. ENTORNO=desarrollo solo aplica a
# este paso: la descarga no necesita SECRET_KEY.
RUN mkdir -p /opt/modelos \
    && ENTORNO=desarrollo python -m cotejo.documentos.descargar_modelo \
    && chown -R cotejo:cotejo /opt/modelos

COPY --chmod=755 scripts/entrypoint.sh ./scripts/entrypoint.sh
COPY datos/ ./datos/
COPY --from=web /web/dist ./static/

ENV HF_HUB_OFFLINE=1

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/salud', timeout=4)"]

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
