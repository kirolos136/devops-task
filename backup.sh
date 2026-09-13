#!/usr/bin/env bash
set -euo pipefail

set -a
source .env
set +a

BACKUP_DIR="backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="${BACKUP_DIR}/barq-${STAMP}.sql"

mkdir -p "$BACKUP_DIR"

echo "Backing up database '${POSTGRES_DB}' to ${FILE}"

docker compose exec -T postgres \
  pg_dump --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "$FILE"

echo "Backup complete: $(wc -l < "$FILE") lines"