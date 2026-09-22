# Vehicules (Flask)

Application Flask de gestion des véhicules.

Projet développé par Mr Alexandre Stephen.

## Comptes utilisateurs et connexion

Il n'y a **pas d'inscription publique**. Les comptes sont créés par un
administrateur depuis *Gestion des utilisateurs → Nouvel utilisateur* en
saisissant uniquement le prénom, le nom et l'adresse e‑mail.

* **Identifiant de connexion** : généré automatiquement sous la forme
  `nom` + `initiale du prénom` (ex. `dupontj`, puis `dupontj2` en cas
  d'homonyme). Il ne change jamais, même si le nom est corrigé ensuite.
* **Mot de passe** : généré aléatoirement par l'application (ex.
  `Kx7m-Rp2v-Q9wT`), affiché **une seule fois** à l'administrateur et envoyé
  par e‑mail à l'utilisateur.
* **L'utilisateur ne peut pas modifier son mot de passe.** En cas d'oubli,
  un super administrateur clique sur *Régénérer le mot de passe* dans la
  liste des utilisateurs.
* **L'adresse e‑mail** ne sert plus qu'aux notifications (réservations,
  validations). Elle n'est jamais utilisée pour se connecter, ce qui évite
  toute réutilisation d'un mot de passe de messagerie professionnelle.

Les variables `SUPERADMIN_EMAILS` / `ADMIN_EMAILS` ne servent plus qu'aux
notifications de secours lorsque aucun destinataire n'est coché dans
« Gestion des congés ».

### Mots de passe et sessions

Le mot de passe généré ne transite **jamais** par le cookie de session : il est
conservé côté serveur (table `credential_handoff`, supprimée dès l'affichage et
au plus tard après 10 minutes), la session ne portant qu'un jeton opaque.

Régénérer un mot de passe **ferme immédiatement les sessions déjà ouvertes** de
l'utilisateur concerné : la session porte une empreinte HMAC du mot de passe
courant, comparée à chaque requête. Un compte compromis est donc réellement
repris en main, sans attendre l'expiration de session.

Conséquence au déploiement : les sessions ouvertes avant cette version n'ont pas
d'empreinte et sont refusées. Chacun se reconnecte une fois, c'est normal.

### Limitation des tentatives de connexion

Chaque tentative de connexion est enregistrée (identifiant saisi, adresse IP,
succès ou échec). Après **5 échecs** sur un même identifiant en 15 minutes,
cet identifiant est bloqué **15 minutes** (« Trop de tentatives échouées »),
même si le bon mot de passe est ensuite saisi. Une connexion réussie remet le
compteur à zéro. Une adresse IP qui accumule 30 échecs en 15 minutes est
bloquée de la même façon, quel que soit l'identifiant. Variables :
`LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_MINUTES`, `LOGIN_IP_MAX_ATTEMPTS`.

Derrière le proxy Caddy, l'adresse du client est lue dans `X-Forwarded-For`.
L'historique est conservé 30 jours et consultable :

```bash
flask login-attempts              # échecs des dernières 24 h
flask login-attempts --hours 168 --all
```

### Commandes de secours (super administrateur)

Si l'interface web n'est pas accessible, ces commandes s'exécutent sur le
serveur (préfixer par `docker compose run --rm vehicules` en déploiement
Docker) :

```bash
flask list-usernames                       # afficher tous les identifiants
flask reset-password <identifiant|email>   # nouveau mot de passe aléatoire
flask set-username <email> <identifiant>   # changer un identifiant
```

Lors de la première mise à jour vers cette version, `flask db upgrade` crée
automatiquement un identifiant pour chaque compte existant et **affiche la
correspondance e‑mail → identifiant** dans le terminal. Les mots de passe
existants restent valables.

## Navigation

La barre du haut contient trois liens permanents : **Accueil**, **Planning** et
**Réserver**, avec la page courante mise en évidence. Auparavant elle n'en
contenait aucun : passer d'une section à l'autre imposait de revenir à
l'accueil par le nom de l'application, puis de cliquer une tuile, et les pages
sans issue (formulaire, contact) n'offraient aucun autre chemin.

Sur téléphone, les libellés et le nom de l'application s'effacent pour ne
laisser que les icônes, sinon la barre passe sur deux lignes. Les tuiles de
l'accueil restent la porte d'entrée vers les pages d'administration.

## Accueil : tableau du jour et annulation

La page d'accueil de chaque rôle affiche :

* **Aujourd'hui** : pour chaque véhicule, son état à l'instant présent —
  *Sorti* (avec qui, jusqu'à quelle heure), *Réservé plus tard* (à partir de
  quelle heure) ou *Libre*. Les réservations validées et leurs segments
  jour par jour sont pris en compte. Les admins voient en plus le nombre de
  demandes en attente.
* **Mes réservations à venir** : les demandes en attente et les réservations
  validées de l'utilisateur, avec un bouton **Annuler**. L'annulation passe
  la réservation au statut `cancelled`, libère immédiatement le véhicule, et
  envoie un e‑mail aux administrateurs notifiés ainsi qu'aux participants.
  Une réservation terminée, refusée ou archivée ne peut plus être annulée.

## Archivage annuel

`tools/archive_year.py` génère un PDF par mois de l'année écoulée
(minuteur systemd le 31 décembre à 23h55) et supprime les archives plus
anciennes que `--keep-years`.

**La base de données n'est pas purgée.** Les réservations restent dans
l'application et le planning reste consultable ; une année pèse quelques
centaines de kilo-octets. La suppression n'a lieu qu'avec `--purge`, à
utiliser en connaissance de cause après vérification des PDF :

```bash
python tools/archive_year.py --year 2026 --dry-run   # simulation
python tools/archive_year.py --year 2026 --purge     # supprime, irréversible
```

Les PDF (export mensuel comme archive annuelle) incluent les segments : une
réservation répartie sur plusieurs véhicules a `vehicle_id = None` et serait
sinon totalement absente du document.

## Fiabilité des opérations

**Échecs d'e-mail.** `send_mail_msmtp` renvoie `(False, "smtp error…")` au lieu
de lever une exception : les `try/except` ne voyaient donc jamais les échecs,
qui passaient inaperçus. Tous les envois passent désormais par `notify()`, qui
journalise l'échec et l'affiche à la personne ayant déclenché l'action, puisque
le destinataire, lui, ne recevra rien. Pour relever les échecs passés :

```bash
docker compose logs vehicules | grep "Echec d'envoi"
```

**Validation simultanée.** Entre la vérification de disponibilité et
l'enregistrement, un autre administrateur peut avoir pris le même véhicule.
`commit_if_still_free()` force l'écriture (SQLite prend alors son verrou),
revérifie dans la même transaction et annule si un conflit est apparu. Le
second administrateur voit « Ce véhicule vient d'être attribué par un autre
administrateur » plutôt que de créer une double réservation.

## Segments et suppressions

Une réservation répartie sur plusieurs véhicules est découpée en *segments*.
Toute suppression de réservation doit emporter ses segments : un segment
orphelin est invisible dans le planning (qui fait une jointure sur la
réservation) mais reste vu par `has_conflict`, ce qui **bloque le véhicule
définitivement alors qu'il paraît libre**. La fonction `delete_reservations()`
supprime toujours les segments d'abord ; elle est utilisée par la purge
quotidienne, la purge des archives et la suppression d'un utilisateur.

Un véhicule utilisé par une réservation ou un segment **ne peut pas être
supprimé** : déclarez-le indisponible, ce qui le retire des attributions sans
perdre l'historique.

Pour nettoyer une base existante (fantômes créés avant ce correctif) :

```bash
flask repair-orphan-segments --dry-run   # afficher sans rien supprimer
flask repair-orphan-segments             # supprimer
```

## Lancer les tests

Sur un poste de développement :

```bash
pip install -r requirements.txt
python -m pytest -q
```

Sur le Raspberry, dans le conteneur Docker (après `docker compose build`) :

```bash
cd /opt/vehicules/app
docker compose run --rm vehicules python -m pytest -q
```

`tests/conftest.py` fournit la `SECRET_KEY` et un serveur mail factice :
aucune variable d'environnement n'est nécessaire, et les tests utilisent une
base en mémoire sans toucher à `instance/vehicules.db`. La suite doit passer
intégralement ; c'est le filet de sécurité avant chaque mise à jour.

## Installation sur téléphone (PWA)

L'application s'installe depuis le navigateur, sans passer par les stores :
icône sur l'écran d'accueil et ouverture en plein écran. La page publique
`/installer` explique la marche à suivre (Chrome sur Android, Safari sur
iPhone/iPad) et un bandeau le propose aux utilisateurs connectés sur mobile.

* `static/manifest.json` – nom, couleurs, icônes PNG (192, 512, maskable).
* `static/icons/` – icônes générées par `python tools/make_icons.py` à partir
  du dessin du favicon (à relancer si le dessin change).
* `/service-worker.js` – servi à la racine (portée `/`). Les pages HTML ne
  sont **jamais** mises en cache (toujours le réseau, page « Pas de
  connexion » hors ligne) ; seuls les fichiers de `/static/` le sont.

L'installation nécessite HTTPS (assuré par le proxy Caddy en production).

## Indisponibilité d'un véhicule

Depuis *Gestion du parc → Indisponibilités*, un administrateur déclare une
période pendant laquelle un véhicule ne peut pas être attribué (panne
mécanique, entretien / contrôle technique, carrosserie, autre), avec une date
de fin facultative (« jusqu'à nouvel ordre »). Effets :

* le véhicule apparaît **Indisponible** sur l'accueil, dans le planning
  mensuel et dans la page de gestion d'une réservation ;
* il ne peut plus être attribué à une réservation ni à un segment sur la
  période (`has_conflict`) ;
* si des réservations validées l'utilisent déjà, l'administrateur est averti
  et la liste des réservations à réattribuer s'affiche avec un lien vers
  chacune.

Le bouton **Lever** supprime l'indisponibilité et rend le véhicule attribuable.

L'heure « maintenant » est calculée dans le fuseau `APP_TIMEZONE` (par
défaut `Europe/Paris`), car les créneaux 8h‑12h / 13h‑17h sont en heure
locale alors que le conteneur Docker tourne en UTC.

## Notifications par e‑mail

* **Annulation par l'utilisateur** – les administrateurs sélectionnés dans
  « Gestion des congés » et les participants reçoivent un e‑mail.

* **Création de compte / régénération de mot de passe** – l'utilisateur
  reçoit ses identifiants de connexion par e‑mail.
* **Activation de compte** – dès qu'un administrateur active un utilisateur, ce
  dernier reçoit une confirmation par e‑mail l'informant que la plateforme est
  accessible.
* **Demandes de réservation** – le demandeur est notifié lors du dépôt de la
  requête puis lors de sa validation. Par ailleurs, les responsables définis
  dans l'onglet « Gestion des congés » reçoivent immédiatement une alerte pour
  pouvoir traiter la demande.

## Promotion/Déclassement

Les rôles des comptes existants peuvent être modifiés via le script CLI :

```bash
python tools/create_admin.py <email> <role>
```

`<role>` peut être `user`, `admin` ou `superadmin`.

## Initialisation de la base de données

Pour repartir sur une base saine :

1. Supprimez l'ancien fichier `instance/vehicules.db` (ou celui défini via `DATABASE_URL`) si nécessaire.
2. Exécutez `flask db upgrade` ou `python seed.py` pour créer la base et appliquer les migrations.

Sans migration appliquée, l'application échouera lors de la connexion avec des erreurs de colonnes manquantes.

Par défaut, l'application utilise la base SQLite située dans `instance/vehicules.db`, c'est-à-dire dans le dossier d'instance de Flask (généralement `<racine-du-projet>/instance`). Assurez-vous que ce répertoire existe et que l'utilisateur disposant du service possède les droits en lecture/écriture. Vous pouvez remplacer cet emplacement en définissant la variable d'environnement `DATABASE_URL` (par exemple `sqlite:////srv/vehicules/data.db`) avant de lancer l'application.

## Segmentation des réservations

Lorsqu'une journée d'une réservation sur plusieurs jours est segmentée vers un autre véhicule, l'application crée désormais des segments pour les jours restants afin de conserver l'attribution initiale du véhicule.

## Contact

Les utilisateurs connectés disposent d'un onglet **Contact** permettant d'envoyer un message aux administrateurs. Les destinataires sont définis via les paramètres de notification et chaque expéditeur reçoit un e‑mail de confirmation.

## Sauvegarde et restauration

Une tâche planifiée exécute `tools/backup_db.sh` chaque jour pour sauvegarder `instance/vehicules.db` (ou le chemin fourni via `DB_PATH`/`DATABASE_URL`) et conserver 30 jours d'historique. Le script envoie automatiquement la sauvegarde vers Google Drive avec [`rclone`](https://rclone.org/).

### Installation et configuration de rclone

```bash
sudo apt-get install rclone
rclone config    # créer le remote « gdrive » de type Google Drive
```

Lors de l'assistant interactif :

1. Choisissez `n` pour créer un nouveau remote puis nommez-le `gdrive`.
2. Sélectionnez le type `drive`.
3. Lorsque rclone propose l'authentification, ouvrez le lien indiqué et connectez-vous avec le compte `gestionvehiculestomer@gmail.com`.
4. Autorisez l'accès Google Drive, puis copiez-collez le code de validation dans le terminal pour finaliser la configuration.

Le fichier de configuration généré est enregistré par défaut dans `~/.config/rclone/rclone.conf`. Pour vérifier son emplacement exact, exécutez :

```bash
rclone config file
```

Notez ensuite le chemin du fichier afin de l'exposer via les variables d'environnement utilisées par le script et le service de sauvegarde :

```bash
export RCLONE_CONFIG=/home/user/.config/rclone/rclone.conf
export REMOTE_URI=gdrive:vehicules-backups
# Indiquez le chemin réel de la base SQLite si différent
export DB_PATH=instance/vehicules.db
# (optionnel) export GDRIVE_SERVICE_ACCOUNT=/chemin/vers/service-account.json
```

Dans `tools/vehicules-backup.service`, ajustez les directives `Environment=DB_PATH=…`, `Environment=RCLONE_CONFIG=…` (et `Environment=GDRIVE_SERVICE_ACCOUNT=…` si vous utilisez un compte de service) pour pointer vers les chemins adaptés avant de relancer le service.

### Installer les minuteurs

Les fichiers de `tools/` sont des modèles : tant qu'ils ne sont pas copiés dans
`/etc/systemd/system/`, rien ne s'exécute automatiquement. Le nom du fichier
devient le nom du service — gardez-le, un minuteur cherche le service de même
nom.

```bash
sudo cp tools/vehicules-backup.service tools/vehicules-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now vehicules-backup.timer
```

Même principe pour l'archivage annuel (31 décembre à 23h55) :

```bash
sudo cp tools/archive_year.service tools/archive_year.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now archive_year.timer
```

Vérifier ce qui est réellement installé et la prochaine exécution :

```bash
systemctl list-timers --all | grep -i vehicul
```

Déclencher une sauvegarde immédiatement, sans attendre le minuteur :

```bash
sudo systemctl start vehicules-backup.service
sudo journalctl -u vehicules-backup.service -n 30 --no-pager
```

La sauvegarde envoie vers `REMOTE_URI` la base, le `.env` et les archives PDF
annuelles (`backups/archives` → `REMOTE_URI/archives`).

### Vérifier une sauvegarde, sans risque

Une sauvegarde qu'on n'a jamais restaurée n'est pas une sauvegarde. Cet
exercice se déroule à côté de la base de production, qui n'est jamais touchée :
on restaure dans un dossier de test, on vérifie, on efface. À refaire après
tout changement touchant aux sauvegardes.

Tout en tant qu'utilisateur applicatif, **sans `sudo`** : lancé en root, rclone
réécrit sa configuration en root et les commandes suivantes échouent.

```bash
# 1. La sauvegarde la plus récente, et le .env qui va avec
rclone lsf gdrive:vehicules-backups --include 'vehicules_*' | sort | tail -3
rclone lsf gdrive:vehicules-backups --include 'env_*' | sort | tail -1

# 2. Télécharger dans un dossier de test, visible depuis le conteneur
mkdir -p instance/restauration-test && cd instance/restauration-test
rclone copy gdrive:vehicules-backups/vehicules_YYYYMMDD_HHMMSS.db.gz .

# 3. Décompresser
gzip -d vehicules_*.db.gz && mv vehicules_*.db restauration.db

# 4. Le fichier est-il sain ? Attendu : « ok », et rien d'autre
sqlite3 restauration.db "PRAGMA integrity_check;"

# 5. Contient-il les mêmes données que la production ?
for t in user vehicle reservation reservation_segment vehicle_unavailability; do
  prod=$(sqlite3 "$DB_PATH" "select count(*) from $t")
  copie=$(sqlite3 restauration.db "select count(*) from $t")
  printf '%-25s production %-6s restauration %s\n' "$t" "$prod" "$copie"
done
```

L'étape suivante est celle qui compte vraiment : un fichier lisible par SQLite
n'est pas forcément exploitable par l'application.

```bash
# 6. L'application sait-elle l'ouvrir ? Conteneur jetable : le service continue
#    de tourner pendant ce temps. Noter les QUATRE barres obliques, trois
#    donneraient un chemin relatif.
docker compose run --rm \
  -e DATABASE_URL=sqlite:////app/instance/restauration-test/restauration.db \
  vehicules python -c "
from app import app
from models import User, Reservation, Vehicle
with app.app_context():
    print('utilisateurs :', User.query.count())
    print('vehicules    :', Vehicle.query.count())
    print('reservations :', Reservation.query.count())
    u = User.query.filter_by(role='superadmin').first()
    print('superadmin   :', u.username if u else 'ABSENT')
"

# 7. Effacer la copie
cd - && rm -rf instance/restauration-test
```

Le compte superadmin doit apparaître : sans lui, la base restaurée laisserait
l'application sans administrateur.

### Restaurer pour de vrai

À ne faire qu'après une perte réelle. Contrairement à l'exercice ci-dessus,
cette procédure écrase la base en service.

```bash
# 1. Arrêter l'application : restaurer sous une base ouverte la corrompt
docker compose stop vehicules

# 2. Mettre de côté la base actuelle, même si on la croit perdue :
#    elle contient peut-être plus que la sauvegarde
cp "$DB_PATH" "$DB_PATH.avant-restauration"

# 3. Récupérer et décompresser la sauvegarde choisie
rclone copy gdrive:vehicules-backups/vehicules_YYYYMMDD_HHMMSS.db.gz backups/
gzip -d backups/vehicules_YYYYMMDD_HHMMSS.db

# 4. Restaurer, puis vérifier AVANT de redémarrer
sqlite3 "$DB_PATH" ".restore 'backups/vehicules_YYYYMMDD_HHMMSS.db'"
sqlite3 "$DB_PATH" "PRAGMA integrity_check;"

# 5. Redémarrer
docker compose start vehicules
```

`DB_PATH` est le chemin déclaré dans `vehicules-backup.service`, par exemple
`/opt/vehicules/app/vehicules/instance/instance/vehicules.db`.

Restaurer la base ne suffit pas à repartir d'une machine neuve : il faut aussi
le `.env` sauvegardé le même jour (`env_YYYYMMDD_HHMMSS.txt`). Il porte la
`SECRET_KEY` — une valeur différente invalide toutes les sessions ouvertes — et
le mot de passe d'envoi des e-mails.

## Licence

Ce projet est distribué sous une licence “Tous droits réservés”.
Toute utilisation, reproduction, modification, distribution ou vente
est interdite sans l’autorisation écrite explicite de l’auteur.
Voir le fichier [LICENSE](LICENSE) pour plus de détails.

## Archivage des réservations

Les réservations approuvées ou rejetées ne sont plus supprimées
immédiatement par la tâche automatique : elles sont d’abord archivées
(`archived_at` est renseigné) afin de rester visibles dans le planning
mensuel et exportables en PDF pendant plusieurs mois.

### Purge manuelle des archives

Une commande CLI est disponible pour effacer définitivement les
réservations archivées plus anciennes qu’un délai donné (180 jours par
défaut) :

```bash
flask purge-archived-reservations
```

Si l’application tourne sur un serveur distant (par exemple un
Raspberry Pi), vous pouvez exécuter cette commande depuis votre terminal
Mac en vous connectant en SSH puis en lançant la commande Flask :

```bash
ssh pi@192.168.1.34
cd /opt/vehicules/app
source venv/bin/activate
export FLASK_APP=app.py
flask purge-archived-reservations
```

Les deux premières lignes établissent la connexion SSH à votre Raspberry Pi
et se placent dans le dossier de l’application. Les deux suivantes activent
l’environnement virtuel Python puis définissent la variable `FLASK_APP`
avant d’exécuter la commande de purge. Adaptez seulement l’adresse IP ou le
chemin si votre installation diffère. Vous pouvez aussi planifier cette
commande (par exemple via `cron`) pour nettoyer les archives à intervalle
régulier.
