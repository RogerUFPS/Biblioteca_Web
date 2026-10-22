#!/bin/sh

set -eu

: "${HARVESTING_API_URL:?HARVESTING_API_URL debe ser la URL base de la API}"
CRON_SCHEDULE="${CRON_SCHEDULE:-* * * * *}"

case "$HARVESTING_API_URL" in
    http://*|https://*) ;;
    *)
        printf 'Error: HARVESTING_API_URL debe comenzar con http:// o https://.\n' >&2
        exit 1
        ;;
esac

case "$HARVESTING_API_URL" in
    *[[:space:]]*)
        printf 'Error: HARVESTING_API_URL no puede contener espacios ni saltos de línea.\n' >&2
        exit 1
        ;;
esac

if ! python3 - "$CRON_SCHEDULE" <<'PY'
import re
import sys

if not re.fullmatch(r"[\d*/,-]+(?: [\d*/,-]+){4}", sys.argv[1]):
    raise SystemExit(1)
PY
then
    printf 'Error: CRON_SCHEDULE debe contener cinco campos con formato cron permitido.\n' >&2
    exit 1
fi

{
    printf 'HARVESTING_API_URL=%s\n' "$HARVESTING_API_URL"
    printf 'CRON_TZ=UTC\n'
    printf '%s su-exec appuser /app/script.sh >> /proc/1/fd/1 2>&1\n' "$CRON_SCHEDULE"
} > /etc/crontabs/root

exec crond -f -l 2 -L /dev/stdout
