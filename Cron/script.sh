#!/bin/sh

set -eu

: "${HARVESTING_API_URL:?HARVESTING_API_URL debe ser la URL base de la API}"

endpoint="${HARVESTING_API_URL%/}/api/harvesting/schedules/run-due/"
response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT HUP INT TERM

if ! http_status="$(
    curl \
        --silent \
        --show-error \
        --output "$response_file" \
        --write-out '%{http_code}' \
        --request POST \
        "$endpoint"
)"; then
    printf 'Error: no se pudo contactar el endpoint de cosechas.\n' >&2
    exit 1
fi

if [ "$http_status" != "200" ] && [ "$http_status" != "202" ]; then
    printf 'Error: el endpoint respondió HTTP %s.\n' "$http_status" >&2
    cat "$response_file" >&2
    printf '\n' >&2
    exit 1
fi

if ! python3 -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as response_file:
    response = json.load(response_file)

if not isinstance(response, list):
    raise SystemExit("La respuesta del endpoint debe ser un arreglo JSON.")

if any(not isinstance(harvest, dict) or "state" not in harvest for harvest in response):
    raise SystemExit("La respuesta contiene un Harvest con formato inesperado.")

failed_ids = [
    str(harvest.get("id", "sin ID"))
    for harvest in response
    if harvest["state"] == "failed"
]
if failed_ids:
    raise SystemExit("Fallaron los Harvest: " + ", ".join(failed_ids))
' "$response_file"; then
    printf 'Error: la respuesta del endpoint no pasó las verificaciones.\n' >&2
    cat "$response_file" >&2
    printf '\n' >&2
    exit 1
fi

cat "$response_file"
printf '\nEndpoint de cosechas verificado correctamente (HTTP %s).\n' "$http_status"
