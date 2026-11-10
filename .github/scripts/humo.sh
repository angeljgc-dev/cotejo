#!/usr/bin/env bash
# Prueba de humo contra el contenedor ya levantado: salud, frontend, entrar a la demo y tablero con datos.
# Uso: .github/scripts/humo.sh [url_base]   (por omisión http://localhost:8000)
set -euo pipefail

BASE="${1:-http://localhost:8000}"
TRABAJO="$(mktemp -d)"
trap 'rm -rf "$TRABAJO"' EXIT
COOKIES="$TRABAJO/cookies.txt"

falla() {
    echo "FALLÓ: $*" >&2
    exit 1
}

echo "Esperando a $BASE/api/salud..."
listo=0
for _ in $(seq 1 60); do
    if curl -fsS "$BASE/api/salud" -o "$TRABAJO/salud.json" 2>/dev/null; then
        listo=1
        break
    fi
    sleep 5
done
[ "$listo" = "1" ] || falla "/api/salud no respondió 200 en 5 minutos"
jq -e '.estado == "ok" and .base == "ok" and .modo_demo == true' "$TRABAJO/salud.json" >/dev/null \
    || falla "salud inesperada: $(cat "$TRABAJO/salud.json")"
echo "ok salud: $(cat "$TRABAJO/salud.json")"

curl -fsS "$BASE/" -o "$TRABAJO/indice.html" || falla "GET / no respondió 200"
grep -q '<div id="raiz"' "$TRABAJO/indice.html" || falla "GET / no devolvió el frontend"
echo "ok frontend"

curl -fsS -c "$COOKIES" -X POST "$BASE/api/sesion/demo" \
    -H "Content-Type: application/json" -H "X-Cotejo: 1" \
    -d '{"rol":"capturista"}' -o "$TRABAJO/sesion.json" || falla "POST /api/sesion/demo no respondió 200"
jq -e '.rol == "capturista" and .es_demo == true' "$TRABAJO/sesion.json" >/dev/null \
    || falla "sesión inesperada: $(cat "$TRABAJO/sesion.json")"
echo "ok sesión demo"

curl -fsS -b "$COOKIES" "$BASE/api/tablero" -o "$TRABAJO/tablero.json" || falla "GET /api/tablero no respondió 200"
jq -e '(.adeudo_total_mxn | tonumber) > 0 and (.por_proveedor | length) > 0' "$TRABAJO/tablero.json" >/dev/null \
    || falla "el tablero no trae datos sembrados: $(head -c 500 "$TRABAJO/tablero.json")"
echo "ok tablero: adeudo total $(jq -r '.adeudo_total_mxn' "$TRABAJO/tablero.json") MXN"

echo "Prueba de humo en verde."
