#!/usr/bin/env bash
set -euo pipefail

# Environment variables:
#   COMPRESS                 Whether to gzip the backup (default: true).
#   REMOTE_URI               rclone destination to receive the backup (optional).
#   RCLONE_CONFIG            Path to a custom rclone configuration file (optional).
#   GDRIVE_SERVICE_ACCOUNT   Path to a Google Drive service account JSON file (optional).

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
  RCLONE_ARGS=()
  if [ -n "${RCLONE_CONFIG:-}" ]; then
    RCLONE_ARGS+=("--config" "$RCLONE_CONFIG")
  fi
  if [ -n "${GDRIVE_SERVICE_ACCOUNT:-}" ]; then
    RCLONE_ARGS+=("--drive-service-account-file" "$GDRIVE_SERVICE_ACCOUNT")
  fi

  if ! rclone "${RCLONE_ARGS[@]}" copy "$DB_FILE" "$REMOTE_URI"; then
    echo "Error: failed to copy backup to remote destination '$REMOTE_URI'" >&2
    exit 1
  fi
fi

find "$BACKUP_DIR" -type f -mtime +30 -name 'vehicules_*' -delete
