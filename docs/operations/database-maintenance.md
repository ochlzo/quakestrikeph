# Database maintenance

## Change database passwords on an existing volume

Run these commands from the repository root on the machine whose database you
want to update: your Windows machine for local data, or the VPS for production
data. Editing `.env` does not change passwords already stored in PostgreSQL.
First, update `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`, and
`WORKER_DB_PASSWORD` in that machine's `.env`, and match the latter two in
`MIGRATION_DATABASE_URL` and `DATABASE_URL`.

Start PostgreSQL with the updated environment, then open `psql`:

```text
docker compose --env-file .env -f infrastructure/compose.yml up -d --wait postgres
docker compose --env-file .env -f infrastructure/compose.yml exec postgres psql -U quakestrike -d quakestrike
```

At the `quakestrike=#` prompt, run `\password quakestrike`, enter the new
`POSTGRES_PASSWORD` twice, then run `\q`. Substitute your configured
`POSTGRES_USER` and `POSTGRES_DB` if they differ from `quakestrike`. Next,
update the migration and worker roles to match `.env`:

```text
docker compose --env-file .env -f infrastructure/compose.yml exec -T postgres sh /opt/quakestrike/provision-roles.sh create
```

If you use pgAdmin, also set `OBSERVER_DB_PASSWORD` in `.env` and update its
read-only database login with `python infrastructure/scripts/create-observer.py`
on Windows or `python3 infrastructure/scripts/create-observer.py` on the VPS.
There is no `observer-init` Compose service. Recreate application containers
through the normal deployment steps so they receive the updated credentials.
Changing `PGADMIN_DEFAULT_PASSWORD` on an existing pgAdmin volume requires a
separate password change in pgAdmin.

## Browse production PostgreSQL over Tailscale

Run this section in an SSH shell on the VPS. Running it from Windows starts or
uses a separate local Compose database and will show local data, not production.

On the VPS, set `OBSERVER_DB_PASSWORD`, `PGADMIN_DEFAULT_EMAIL`, and
`PGADMIN_DEFAULT_PASSWORD` in the ignored `.env` file. Use distinct, strong
passwords. Apply migrations first, then create the read-only login and start
the optional pgAdmin container:

```bash
python3 infrastructure/scripts/create-observer.py
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.admin.yml --profile admin up -d --wait pgadmin
sudo tailscale serve --bg --https=443 http://127.0.0.1:5050
tailscale serve status
```

Run these commands from the repository root after the production stack and
Tailscale are running. The last command prints the private `https://...ts.net`
address. Open it from a device connected to the tailnet. Sign in to pgAdmin,
then register a server with host `postgres`, port `5432`, the configured
`POSTGRES_DB` name, user `quakestrike_observer`, and
`OBSERVER_DB_PASSWORD`. Refresh a table or rerun a query to see new committed
production data. The read-only login cannot edit application records.
The observer script uses the PostgreSQL container's local connection. If you
changed passwords in `.env` on an existing VPS database, follow
[the password change steps](#change-database-passwords-on-an-existing-volume)
to keep the other database logins aligned.

The pgAdmin web port binds only to `127.0.0.1` on the VPS. Do not change it to
`5050:80`: Docker-published ports can bypass UFW. Keep the Tailscale Serve
route private to authorized operators in tailnet policy. PostgreSQL port 5432
remains unpublished. pgAdmin has its own login and persistent settings volume.
Changing `PGADMIN_DEFAULT_PASSWORD` in `.env` after first initialization does
not rotate an existing pgAdmin account password; change that password in
pgAdmin.

To disable the private browser on the VPS:

```bash
sudo tailscale serve --https=443 off
docker compose --env-file .env -f infrastructure/compose.yml -f infrastructure/compose.admin.yml --profile admin stop pgadmin
```

