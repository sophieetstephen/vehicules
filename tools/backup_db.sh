#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
DB_FILE="$BACKUP_DIR/vehicules_${TS}.db"

sqlite3 vehicules.db ".backup '$DB_FILE'"

if [ "${COMPRESS:-true}" = "true" ]; then
  gzip "$DB_FILE"
  DB_FILE="${DB_FILE}.gz"
fi

if [ -n "${REMOTE_URI:-}" ]; then
  rclone copy "$DB_FILE" "$REMOTE_URI"
fi

find "$BACKUP_DIR" -type f -mtime +30 -name 'vehicules_*' -delete
