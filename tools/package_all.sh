#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vehicules"
DATE="$(date +%F)"
ARCHIVE="/opt/vehicules_${DATE}.tgz"
SCHEMA_ROOT="/opt/schema_root_${DATE}.sql"
SCHEMA_INSTANCE="/opt/schema_instance_${DATE}.sql"
REPORT="/opt/rapport_${DATE}.txt"

echo "=== Préparation du package complet (${DATE}) ==="

# 1) Archive du code (sans .git/.venv/data)
tar czf "$ARCHIVE" \
  --exclude="${APP_DIR}/.git" \
  --exclude="${APP_DIR}/.venv" \
  --exclude="${APP_DIR}/data" \
  --exclude='*.log' \
  -C /opt vehicules
echo "✓ Archive créée : $ARCHIVE"

# 2) Export schémas SQLite (si sqlite3 dispo)
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "Installation sqlite3..."
  sudo apt-get update && sudo apt-get install -y sqlite3
fi

if [ -f "/opt/vehicules/vehicules.db" ]; then
  sqlite3 "/opt/vehicules/vehicules.db" '.schema' > "$SCHEMA_ROOT"
  echo "✓ Schéma root exporté : $SCHEMA_ROOT"
fi

if [ -f "/opt/vehicules/instance/vehicules.db" ]; then
  sqlite3 "/opt/vehicules/instance/vehicules.db" '.schema' > "$SCHEMA_INSTANCE"
  echo "✓ Schéma instance exporté : $SCHEMA_INSTANCE"
fi

# 3) Rapport d’état Git (si git dispo)
cd "$APP_DIR"
{
  echo "=== Rapport du ${DATE} ==="
  echo
  echo ">> git status"
  git status || echo "git non initialisé"
  echo
  echo ">> git log --since='2 days ago' --oneline"
  git log --since='2 days ago' --oneline || true
} > "$REPORT"
echo "✓ Rapport généré : $REPORT"

echo "=== Terminé ==="
echo "Fichiers prêts :"
ls -lh "$ARCHIVE" "$SCHEMA_ROOT" "$SCHEMA_INSTANCE" "$REPORT" 2>/dev/null
