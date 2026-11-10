#!/bin/sh
# Arranque del contenedor: migra la base, siembra la demo si hace falta y arranca el servidor.
set -eu

# Solo docker-compose activa CLAVE_TEMPORAL_SI_FALTA. En un hospedaje real SECRET_KEY es obligatoria y la app
# se niega a arrancar sin ella.
if [ -z "${SECRET_KEY:-}" ] && [ "${CLAVE_TEMPORAL_SI_FALTA:-0}" = "1" ]; then
    SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
    export SECRET_KEY
    echo "SECRET_KEY no está definida: se generó una temporal. Las sesiones se pierden al reiniciar." >&2
fi

echo "Aplicando migraciones..."
alembic upgrade head

# La decisión la toma Python con la misma configuración que la app, así "1", "true" o "si" se leen igual.
accion="$(python - <<'PY'
from sqlalchemy import text

from cotejo.config import obtener_config
from cotejo.db import obtener_motor

if obtener_config().sembrar_si_vacia:
    with obtener_motor().connect() as conexion:
        vacia = conexion.execute(text("SELECT NOT EXISTS (SELECT 1 FROM facturas)")).scalar_one()
    print("sembrar" if vacia else "")
PY
)"

if [ "$accion" = "sembrar" ]; then
    echo "Base vacía: sembrando datos ficticios..."
    python -m cotejo.semilla
fi

# Un solo worker: el modelo de embeddings ocupa cerca de 1 GB por proceso.
exec uvicorn cotejo.api.app:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
