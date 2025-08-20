#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/vehicules"
DATA_DIR="${APP_DIR}/data"
DATE="$(date +%F)"

echo "=== Génération de l'archive du ${DATE} ==="

cd "$APP_DIR"

# 1) Activer l'environnement virtuel
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
else
  echo "⚠️  Attention : pas de .venv trouvé dans ${APP_DIR}"
fi

# 2) Générer requirements.txt
if command -v pip >/dev/null 2>&1; then
  pip freeze > requirements.txt
  echo "✓ requirements.txt généré"
fi

# 3) Générer le schéma SQLite
if [ -f "${DATA_DIR}/app.db" ]; then
  SCHEMA="schema_${DATE}.sql"
  sqlite3 "${DATA_DIR}/app.db" '.schema' > "$SCHEMA"
  echo "✓ Schéma SQLite exporté : $SCHEMA"
else
  echo "⚠️  Base SQLite non trouvée (${DATA_DIR}/app.db)"
fi

# 4) Créer l’archive
ARCHIVE="/opt/vehicules_${DATE}.tgz"
tar czf "$ARCHIVE" \
  --exclude="${APP_DIR}/.git" \
  --exclude="${APP_DIR}/.venv" \
  --exclude="${APP_DIR}/data" \
  --exclude='*.log' \
  -C /opt vehicules

echo "✓ Archive créée : $ARCHIVE"
echo "=== Terminé ==="
