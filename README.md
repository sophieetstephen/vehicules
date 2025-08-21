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
