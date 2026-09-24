#!/usr/bin/env bash
set -euo pipefail

# Environment variables:
#   DB_PATH                  Path to the SQLite database file. Overrides DATABASE_URL.
#   DATABASE_URL             SQLAlchemy-style database URL (sqlite:// or file:// URLs are supported).
#   ENV_FILE                 Path to .env file to backup (optional).
#   COMPRESS                 Whether to gzip the backup (default: true).
#   REMOTE_URI               rclone destination to receive the backup (optional).
#   ARCHIVE_DIR              Directory holding the yearly PDF archives
#                            (default: backups/archives). Copied to
#                            REMOTE_URI/archives when REMOTE_URI is set.
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

ENV_FILE="${ENV_FILE:-.env}"
ENV_BACKUP=""
if [ -f "$ENV_FILE" ]; then
  ENV_BACKUP="$BACKUP_DIR/env_${TS}.txt"
  cp "$ENV_FILE" "$ENV_BACKUP"
  # Le .env contient des secrets (mot de passe mail, SECRET_KEY) :
  # lisible uniquement par l'utilisateur qui sauvegarde.
  chmod 600 "$ENV_BACKUP"
fi

if [ -n "${REMOTE_URI:-}" ]; then
  # ${RCLONE_ARGS[@]+...} plutot que "${RCLONE_ARGS[@]}" : sous « set -u »,
  # un tableau vide fait echouer bash avant 4.4 (celui de macOS, releve par
  # l'audit).
  RCLONE_ARGS=()
  if [ -n "${RCLONE_CONFIG:-}" ]; then
    RCLONE_ARGS+=("--config" "$RCLONE_CONFIG")
  fi
  if [ -n "${GDRIVE_SERVICE_ACCOUNT:-}" ]; then
    RCLONE_ARGS+=("--drive-service-account-file" "$GDRIVE_SERVICE_ACCOUNT")
  fi

  # La destination chiffre-t-elle ce qu'on lui envoie ? Le .env porte la cle
  # de session : avec elle et la base, deposees au meme endroit, on peut se
  # connecter en superadministrateur sans connaitre aucun mot de passe. Il ne
  # part donc que vers un remote rclone de type « crypt ».
  REMOTE_NAME="${REMOTE_URI%%:*}"
  REMOTE_TYPE=""
  if [ "$REMOTE_NAME" != "$REMOTE_URI" ]; then
    REMOTE_TYPE="$(rclone ${RCLONE_ARGS[@]+"${RCLONE_ARGS[@]}"} listremotes --long 2>/dev/null \
      | awk -v nom="${REMOTE_NAME}:" '$1 == nom { print $2 }')"
  fi
  if [ "$REMOTE_TYPE" != "crypt" ]; then
    echo "Attention : '$REMOTE_URI' n'est pas une destination chiffree ; la base y part en clair et le .env n'y sera pas envoye." >&2
  fi

  if ! rclone ${RCLONE_ARGS[@]+"${RCLONE_ARGS[@]}"} copy "$DB_FILE" "$REMOTE_URI"; then
    echo "Error: failed to copy backup to remote destination '$REMOTE_URI'" >&2
    exit 1
  fi

  if [ -n "$ENV_BACKUP" ] && [ "$REMOTE_TYPE" = "crypt" ]; then
    if ! rclone ${RCLONE_ARGS[@]+"${RCLONE_ARGS[@]}"} copy "$ENV_BACKUP" "$REMOTE_URI"; then
      echo "Error: failed to copy .env backup to remote destination '$REMOTE_URI'" >&2
      exit 1
    fi
  fi

  # Les PDF d'archive sont la trace permanente qui justifie, a terme, de
  # supprimer les reservations de l'annee. Ils ne partaient nulle part : une
  # panne du SSD les emportait tous. rclone copy est incremental, seuls les
  # fichiers nouveaux traversent le reseau.
  ARCHIVE_DIR="${ARCHIVE_DIR:-$BACKUP_DIR/archives}"
  if [ -d "$ARCHIVE_DIR" ]; then
    if ! rclone ${RCLONE_ARGS[@]+"${RCLONE_ARGS[@]}"} copy "$ARCHIVE_DIR" "${REMOTE_URI%/}/archives"; then
      echo "Error: failed to copy PDF archives to '${REMOTE_URI%/}/archives'" >&2
      exit 1
    fi
  fi
fi

find "$BACKUP_DIR" -type f -mtime +30 -name 'vehicules_*' -delete
find "$BACKUP_DIR" -type f -mtime +30 -name 'env_*' -delete
