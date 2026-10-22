#!/bin/sh

set -eu

: "${HARVESTING_API_URL:?HARVESTING_API_URL debe ser la URL base de la API}"
CRON_SCHEDULE="${CRON_SCHEDULE:-* * * * *}"

{
    printf 'HARVESTING_API_URL=%s\n' "$HARVESTING_API_URL"
    printf 'CRON_TZ=UTC\n'
    printf '%s su-exec appuser /app/script.sh >> /proc/1/fd/1 2>&1\n' "$CRON_SCHEDULE"
} > /etc/crontabs/root

exec crond -f -l 2 -L /dev/stdout
