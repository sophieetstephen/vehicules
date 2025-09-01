# Vehicules (Flask)

Application Flask de gestion des véhicules.

## Rôles administratifs

Lors de la création d'un compte via `/register` ou `/first_login`,
l'application vérifie si l'adresse e‑mail figure dans les variables
d'environnement `SUPERADMIN_EMAILS` ou `ADMIN_EMAILS`.

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

## Contact

Les utilisateurs connectés disposent d'un onglet **Contact** permettant d'envoyer un message aux administrateurs. Les destinataires sont définis via les paramètres de notification et chaque expéditeur reçoit un e‑mail de confirmation.
