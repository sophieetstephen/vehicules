# Vehicules (Flask)

Application Flask de gestion des véhicules.

Projet développé par Mr Alexandre Stephen.

## Rôles administratifs

Lors de l'inscription via la page `/register`, l'application vérifie si l'adresse e‑mail figure dans les variables d'environnement `SUPERADMIN_EMAILS` ou `ADMIN_EMAILS` afin d'attribuer automatiquement le rôle approprié.

* `SUPERADMIN_EMAILS` – adresses séparées par des virgules qui recevront le
  rôle `superadmin`.
* `ADMIN_EMAILS` – adresses séparées par des virgules qui recevront le rôle
  `admin`.

## Promotion/Déclassement

Les rôles des comptes existants peuvent être modifiés via le script CLI :

```bash
python tools/create_admin.py <email> <role>
```

`<role>` peut être `user`, `admin` ou `superadmin`.

## Initialisation de la base de données

Pour repartir sur une base saine :

1. Supprimez l'ancien fichier `vehicules.db` si nécessaire.
2. Exécutez `flask db upgrade` ou `python seed.py` pour créer la base et appliquer les migrations.

Sans migration appliquée, l'application échouera lors de la connexion avec des erreurs de colonnes manquantes.

## Segmentation des réservations

Lorsqu'une journée d'une réservation sur plusieurs jours est segmentée vers un autre véhicule, l'application crée désormais des segments pour les jours restants afin de conserver l'attribution initiale du véhicule.

## Contact

Les utilisateurs connectés disposent d'un onglet **Contact** permettant d'envoyer un message aux administrateurs. Les destinataires sont définis via les paramètres de notification et chaque expéditeur reçoit un e‑mail de confirmation.

## Sauvegarde et restauration

Une tâche planifiée exécute `tools/backup_db.sh` chaque jour pour sauvegarder `vehicules.db` et conserver 30 jours d'historique.
Le script envoie automatiquement la sauvegarde vers Google Drive avec
[`rclone`](https://rclone.org/).

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
# (optionnel) export GDRIVE_SERVICE_ACCOUNT=/chemin/vers/service-account.json
```

Dans `tools/backup_db.service`, ajustez la directive `Environment=RCLONE_CONFIG=…` (et `Environment=GDRIVE_SERVICE_ACCOUNT=…` si vous utilisez un compte de service) pour pointer vers ces fichiers avant de relancer le service.

### Restaurer depuis Google Drive

```bash
# Télécharger la sauvegarde depuis Drive
rclone copy gdrive:vehicules-backups/vehicules_YYYYMMDD_HHMMSS.db.gz backups/

# Décompresser puis restaurer dans SQLite
gzip -d backups/vehicules_YYYYMMDD_HHMMSS.db.gz
sqlite3 vehicules.db ".restore 'backups/vehicules_YYYYMMDD_HHMMSS.db'"
```

## Licence

Ce projet est distribué sous une licence “Tous droits réservés”.
Toute utilisation, reproduction, modification, distribution ou vente
est interdite sans l’autorisation écrite explicite de l’auteur.
Voir le fichier [LICENSE](LICENSE) pour plus de détails.
