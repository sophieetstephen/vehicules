# Axes d'amélioration - Application Vehicules

## Prioritaires

### 1. Page "Mes Réservations" pour les utilisateurs
- **Problème** : Les utilisateurs n'ont aucun moyen de voir le statut de leurs demandes (approuvée/en attente/refusée)
- **Solution** : Créer une page `/my-reservations` accessible depuis le dashboard
- **Impact** : Réduit les questions aux admins, améliore l'expérience utilisateur

### 2. Bouton "Annuler ma demande"
- **Problème** : Un utilisateur ne peut pas annuler sa propre réservation s'il s'est trompé
- **Solution** : Ajouter un bouton d'annulation sur la page "Mes Réservations"
- **Impact** : Réduit la charge de travail admin

### ~~3. Notifications email (approbation/refus)~~ ✅ FAIT
- ~~**Problème** : L'utilisateur n'est pas notifié quand sa demande est approuvée/refusée/modifiée~~
- ~~**Solution** : Envoyer un email lors de l'approbation, du refus ou de la modification~~
- Emails unifiés : "Véhicule attribué", "Demande refusée", "Réservation supprimée"

---

## Moyennes

### 4. Filtres dans les listes admin
- Filtrer les réservations par date, véhicule, statut
- Filtrer les utilisateurs par rôle, statut
- Recherche dans les véhicules

### 5. Profil utilisateur
- Permettre à l'utilisateur de changer son mot de passe
- Modifier son nom/prénom

### 6. Journal d'audit
- Qui a approuvé quoi et quand
- Historique des modifications

### 7. Approbation en lot
- Approuver plusieurs demandes d'un coup
- Bulk delete des anciennes demandes

---

## Corrections effectuées (18/12/2024)

- [x] Template inscription : aligné "8 caractères" avec le code
- [x] Service worker : corrigé styles.css → custom.css
- [x] Contraste badges : amélioré lisibilité warning/secondary
- [x] Vue mobile calendrier : liste par jour au lieu du tableau
- [x] Suppression légende planning mensuel
- [x] Unification couleurs planning (tout en vert)
- [x] Suppression légende PDF planning
- [x] Dates en français dans gestion réservation
- [x] Interface unifiée gestion réservation
- [x] Archivage automatique quotidien (7 jours)
- [x] Archivage annuel PDF (31 décembre)
- [x] Sécurité CSRF activée
- [x] SECRET_KEY obligatoire en production
- [x] Routes destructives en POST

---

## Notes techniques

- **Déploiement** : Raspberry Pi 5, Docker, ~150 utilisateurs
- **Stack** : Flask, SQLAlchemy, SQLite, WeasyPrint (PDF)
- **Timers systemd** :
  - `archive_reservations.timer` : quotidien à 2h
  - `archive_year.timer` : 31 décembre à 23:55
