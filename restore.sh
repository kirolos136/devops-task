#!/usr/bin/env bash
set -euo pipefail

set -a
source .env
set +a

if [ $# -ne 1 ]; then
  echo "Usage: $0 <backup-file>" >&2
  exit 1
fi

FILE="$1"

if [ ! -f "$FILE" ]; then
  echo "Backup file not found: $FILE" >&2
  exit 1
fi

echo "Restoring ${FILE} into database '${POSTGRES_DB}'"

docker compose exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$FILE"

echo "Restore complete"