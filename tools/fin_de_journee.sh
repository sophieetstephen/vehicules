#!/usr/bin/env bash
set -euo pipefail

REPO="/opt/vehicules"
cd "$REPO"

DATE="$(date +%Y-%m-%d)"
TS="$(date +%Y%m%d_%H%M%S)"

echo "== Fin de journée - $DATE =="
echo "Répertoire: $REPO"

# Purge quotidienne des demandes de réservation expirées
flask --app app purge-expired-requests >/dev/null 2>&1 || true

# 1) Patch des changements non commités (inclut l'intention d'ajout des nouveaux fichiers)
#    -N : enregistre l’intention d’ajouter les nouveaux fichiers sans les indexer totalement
git add -N . >/dev/null 2>&1 || true
UNCOMMITTED_PATCH="working_changes_${TS}.patch"
git diff > "$UNCOMMITTED_PATCH" || true

if [ -s "$UNCOMMITTED_PATCH" ]; then
  echo "✓ Patch des changements NON commités : $UNCOMMITTED_PATCH"
else
  echo "• Aucun changement non commité. (Pas de $UNCOMMITTED_PATCH)"
  rm -f "$UNCOMMITTED_PATCH"
fi

# 2) Patch des commits du jour (si des commits ont été faits aujourd'hui)
#    On cherche le premier commit d'aujourd'hui ; s'il existe, on diffère jusqu'à HEAD
FIRST_TODAY="$(git rev-list -1 --since='00:00' HEAD || true)"
if [ -n "${FIRST_TODAY:-}" ]; then
  COMMITS_PATCH="commits_today_${TS}.patch"
  git diff "${FIRST_TODAY}^" HEAD > "$COMMITS_PATCH" || true
  if [ -s "$COMMITS_PATCH" ]; then
    echo "✓ Patch des COMMITS du jour : $COMMITS_PATCH"
  else
    echo "• Aucun diff entre les commits d'aujourd'hui et HEAD. (Pas de $COMMITS_PATCH)"
    rm -f "$COMMITS_PATCH"
  fi
else
  echo "• Aucun commit effectué aujourd'hui."
fi

# 3) Petit rapport d'état pour ton suivi
REPORT="rapport_fin_de_journee_${TS}.txt"
{
  echo "=== Rapport fin de journée - $DATE ==="
  echo
  echo ">> git status"
  git status
  echo
  echo ">> git log --since='00:00' --oneline"
  git log --since='00:00' --oneline || true
  echo
  echo ">> Fichiers potentiellement modifiés aujourd'hui (heuristique mtime)"
  # Liste indicative (mtime) — purement informatif
  find . -type f -not -path '*/\.git/*' -mtime -1 2>/dev/null | sort || true
} > "$REPORT"

echo "✓ Rapport généré : $REPORT"
echo
echo "Terminé. Envoie-moi le(s) fichier(s) .patch (et le rapport si tu veux)."
