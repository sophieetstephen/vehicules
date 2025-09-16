#!/usr/bin/env bash
set -euo pipefail

# Environment variables:
#   DB_PATH                  Path to the SQLite database file. Overrides DATABASE_URL.
#   DATABASE_URL             SQLAlchemy-style database URL (sqlite:// or file:// URLs are supported).
#   COMPRESS                 Whether to gzip the backup (default: true).
#   REMOTE_URI               rclone destination to receive the backup (optional).
#   RCLONE_CONFIG            Path to a custom rclone configuration file (optional).
#   GDRIVE_SERVICE_ACCOUNT   Path to a Google Drive service account JSON file (optional).

DB_PATH="${DB_PATH:-${1:-}}"

if [ -z "$DB_PATH" ] && [ -n "${DATABASE_URL:-}" ]; then
  DB_PATH="$(python3 - <<'PY'
import os
from urllib.parse import urlparse

db_url = os.environ["DATABASE_URL"]
parsed = urlparse(db_url)

if parsed.scheme and parsed.scheme not in {"sqlite", "file"}:
    raise SystemExit(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

if parsed.scheme in {"sqlite", "file"}:
    netloc = "" if parsed.netloc in {"", "localhost"} else f"/{parsed.netloc}"
    if parsed.path.startswith("//"):
        effective_path = parsed.path[1:]
    else:
        effective_path = parsed.path.lstrip("/")
    path = f"{netloc}{effective_path}"
else:
    path = db_url

if not path:
    raise SystemExit("DATABASE_URL does not contain a database path")

if not os.path.isabs(path):
    path = os.path.abspath(path)

print(path)
PY
)"
fi

if [ -z "$DB_PATH" ]; then
  echo "Error: database path not provided. Set DB_PATH or DATABASE_URL." >&2
  exit 1
fi

if [ ! -f "$DB_PATH" ]; then
  echo "Error: database file '$DB_PATH' not found." >&2
  exit 1
fi

BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"

TS="$(date +%Y%m%d_%H%M%S)"
DB_FILE="$BACKUP_DIR/vehicules_${TS}.db"

sqlite3 "$DB_PATH" ".backup '$DB_FILE'"

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
