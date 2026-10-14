"""The private reader refuses a connection with broader application privileges."""

from sqlalchemy import Engine, func, select, text

from quakestrike.infrastructure.database.account_tables import users

ACCOUNT_COLUMNS = (
    "user_id display_name email email_verified_at email_enabled mobile_number "
    "mobile_verified_at sms_enabled alert_trigger_magnitude nearby_alerts_only "
    "alert_location_latitude alert_location_longitude alert_trigger_distance_km "
    "account_status onboarding_completed_at"
).split()

ACCESS_CHECK = text("""
SELECT current_user = 'quakestrike_alert_testing'
 AND NOT (SELECT rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls
          FROM pg_roles WHERE rolname = current_user)
 AND NOT EXISTS (
   SELECT 1 FROM pg_auth_members
   WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)
 )
 AND NOT has_schema_privilege(current_user, 'public', 'CREATE')
 AND NOT has_column_privilege(current_user, 'public.users', 'clerk_user_id', 'SELECT')
 AND NOT has_column_privilege(current_user, 'public.users', 'created_at', 'SELECT')
 AND NOT has_column_privilege(current_user, 'public.users', 'updated_at', 'SELECT')
 AND NOT EXISTS (
   SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m') AND (
     has_any_column_privilege(current_user, c.oid, 'INSERT,UPDATE')
     OR has_table_privilege(current_user, c.oid, 'DELETE,TRUNCATE,TRIGGER')
     OR (c.relname <> 'users' AND has_any_column_privilege(current_user, c.oid, 'SELECT'))
   )
 )
""")


class AccountAccessUnavailable(Exception):
    pass


class PostgresAccountReader:
    def __init__(self, engine: Engine):
        self.engine = engine

    def search(self, query: str, selected: list[str] | None, page: int, size: int) -> dict:
        predicate = users.c.display_name.ilike(query, escape="\\") | users.c.email.ilike(
            query, escape="\\"
        )
        if selected is not None:
            predicate &= users.c.user_id.in_(selected)
        with self.engine.connect() as connection, connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '2s'"))
            if not connection.scalar(ACCESS_CHECK):
                raise AccountAccessUnavailable
            total = connection.scalar(select(func.count()).select_from(users).where(predicate))
            pages = max(1, (total + size - 1) // size)
            page = min(page, pages)
            rows = (
                connection.execute(
                    select(*(users.c[key] for key in ACCOUNT_COLUMNS))
                    .where(predicate)
                    .order_by(users.c.display_name, users.c.user_id)
                    .offset((page - 1) * size)
                    .limit(size)
                )
                .mappings()
                .all()
            )
        return {"accounts": rows, "total": total, "page": page, "pages": pages}
