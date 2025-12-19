# Axes d'amélioration - Application Vehicules

## Prioritaires - Résolus

### ~~1. Page "Mes Réservations"~~ ✅ NON NÉCESSAIRE
- Les notifications email informent l'utilisateur du statut de ses demandes

### ~~2. Annuler une demande~~ ✅ VIA CONTACT
- Option "Annuler une réservation" dans le formulaire de contact

### ~~3. Notifications email~~ ✅ FAIT
- Emails unifiés : "Véhicule attribué", "Demande refusée", "Réservation supprimée"

### ~~4. Changer mot de passe~~ ✅ VIA CONTACT
- Option "Changer mon mot de passe" dans le formulaire de contact
- Le superadmin réinitialise via gestion utilisateurs

---

## Améliorations optionnelles

### Filtres dans les listes admin
- Filtrer les réservations par date, véhicule, statut
- Filtrer les utilisateurs par rôle, statut

### Journal d'audit
- Qui a approuvé quoi et quand
- Historique des modifications

### Approbation en lot
- Approuver plusieurs demandes d'un coup

---

## Corrections effectuées (18-19/12/2024)

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
- [x] Vue mobile admin_reservations : cartes au lieu du tableau
- [x] Vue mobile admin_users : cartes avec avatar et actions groupées
- [x] Vue mobile admin_vehicles : cartes avec code et libellé
- [x] Vue mobile manage_reservation : grille véhicules 2 colonnes
- [x] Navbar mobile : menu utilisateur toujours visible
- [x] Navbar mobile : bouton thème avec contraste amélioré
- [x] Formulaire contact : menu objet (annulation, mot de passe, etc.)
- [x] Formulaire réservation : pré-remplissage nom/prénom

---

## Notes techniques

- **Déploiement** : Raspberry Pi 5, Docker, ~150 utilisateurs
- **Stack** : Flask, SQLAlchemy, SQLite, WeasyPrint (PDF)
- **Timers systemd** :
  - `archive_reservations.timer` : quotidien à 2h
  - `archive_year.timer` : 31 décembre à 23:55
