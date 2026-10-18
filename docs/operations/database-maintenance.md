# Maintain or inspect the database

| Task | Environment |
| --- | --- |
| [Change database passwords](#change-database-passwords-on-an-existing-volume) | Local machine or VPS that owns the database. |
| [Open production pgAdmin](#browse-production-postgresql-over-tailscale) | Bash on the VPS only. |
| [Disable production pgAdmin](#disable-the-private-database-browser) | Bash on the VPS only. |

Use [PostgreSQL backups](postgres-backups.md) for backup and recovery requirements.

## Change database passwords on an existing volume

Editing `.env` does not change passwords already stored in PostgreSQL.
Run from the repository root on the machine whose database you want to update.
For production, use a maintenance window and the established deployment procedure to pause applications and apply new credentials.

1. Update `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`, and `WORKER_DB_PASSWORD` in that machine's `.env`.
2. Match `MIGRATION_DATABASE_URL` and `DATABASE_URL` to their respective passwords.
3. Start PostgreSQL with the updated environment.

```text
docker compose --env-file .env -f infrastructure/compose.yml up -d --wait postgres
```

4. Open `psql`.

```text
docker compose --env-file .env -f infrastructure/compose.yml exec postgres psql -U quakestrike -d quakestrike
```

Use your configured `POSTGRES_USER` and `POSTGRES_DB` if they differ from `quakestrike`.

5. At the database prompt, run `password quakestrike`.
6. Enter the new `POSTGRES_PASSWORD` twice.
7. Run `q` to exit.
8. Update migration and worker passwords through role provisioning.

```text
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create
```

9. If pgAdmin is enabled, update `OBSERVER_DB_PASSWORD` in `.env`.
10. If that value changed, run the observer script for your operating system.

| Environment | Command |
| --- | --- |
| Windows | `python database/initialization/create-observer.py` |
| VPS | `python3 database/initialization/create-observer.py` |

11. Recreate application containers through the normal local or production procedure.
12. Confirm application health with the new credentials.

**Other logins:** Update `BACKEND_DB_PASSWORD` and `BACKEND_DATABASE_URL` together when rotating the Backend login.
Apply `create-backend` through the [Backend procedure](backend-api.md#manually-upgrade-an-existing-backend).
Private testing uses its [separate restricted login](alert-testing.md#restricted-account-connection).

There is no `observer-init` Compose service.
On an existing pgAdmin volume, change the pgAdmin account password inside pgAdmin.
Changing `PGADMIN_DEFAULT_PASSWORD` in `.env` does not rotate that account.

## Browse production PostgreSQL over Tailscale

**Environment:** SSH shell on the VPS, checkout `/srv/quakestrikeph`.
**Prerequisites:** Production PostgreSQL and Tailscale run; migrations are applied; tailnet policy admits only authorized operators.

Running these commands on Windows opens local data rather than production data.
The private pgAdmin browser has its own login and persistent settings volume.
It provides read-only investigation access separately from the Operations Console.

1. Set `OBSERVER_DB_PASSWORD`, `PGADMIN_DEFAULT_EMAIL`, and `PGADMIN_DEFAULT_PASSWORD` in the ignored VPS `.env`.
2. Use distinct passwords for the database login and pgAdmin account.
3. Create the observer login.

```bash
python3 database/initialization/create-observer.py
```

4. Start pgAdmin.

```bash
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.admin.yml --profile admin up -d --wait pgadmin
```

5. Enable the private HTTPS listener.

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:5050
tailscale serve status
```

6. Open the displayed `https://...ts.net` URL from a permitted tailnet device.
7. Sign in with the configured pgAdmin account.
8. Register a server with these settings.

| Field | Value |
| --- | --- |
| Host | `postgres` |
| Port | `5432` |
| Database | Configured `POSTGRES_DB`. |
| User | `quakestrike_observer` |
| Password | `OBSERVER_DB_PASSWORD` |

Refresh a table or rerun a query to see new committed data. The observer login cannot edit application records.
If passwords changed on an existing volume, complete [password rotation](#change-database-passwords-on-an-existing-volume) first.

Keep pgAdmin bound to `127.0.0.1:5050`. Keep PostgreSQL port 5432 unpublished.
Do not replace the loopback mapping with `5050:80`; Docker-published ports can bypass UFW.

## Disable the private database browser

Remove only the pgAdmin listener, then stop pgAdmin.

```bash
sudo tailscale serve --https=443 off
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.admin.yml --profile admin stop pgadmin
```

The private alert-testing tool uses a separate listener on 8443. Preserve that listener when it is needed.
