"""Passive channel configuration and read-only restricted-worker capability gates."""

from dataclasses import dataclass

from sqlalchemy import text

from quakestrike.application.startup import GateResult
from quakestrike.infrastructure.database.engine import create_database_engine
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider, valid_brevo_configuration
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider
from quakestrike.infrastructure.startup import phase_one_startup_gates


def configured_alert_providers(settings, *, channels=("sms", "email")):
    """Validate selected configuration without network calls or secret-bearing errors."""
    if not channels or set(channels) - {"sms", "email"}:
        raise ValueError("Select SMS or email delivery channels.")
    providers = {}
    if "sms" in channels:
        token = settings.iprog_api_token
        if token is None or not token.get_secret_value().strip():
            raise ValueError("SMS provider configuration is unavailable.")
        providers["sms"] = IprogAlertProvider(token.get_secret_value())
    if "email" in channels:
        key = settings.brevo_api_key
        email, name = settings.brevo_sender_email, settings.brevo_sender_name
        if not valid_brevo_configuration(key.get_secret_value() if key else None, email, name):
            raise ValueError("Alert email provider configuration is unavailable.")
        providers["email"] = BrevoEmailProvider(key.get_secret_value(), email, name)
    return providers


def alert_capabilities(connection):
    ready = connection.scalar(
        text("""
        SELECT current_user = 'quakestrike_worker'
          AND has_table_privilege(current_user, 'alert_jobs', 'SELECT')
          AND has_table_privilege(current_user, 'alert_recipients', 'SELECT')
          AND has_table_privilege(current_user, 'alert_recipients', 'INSERT')
          AND has_table_privilege(current_user, 'alert_delivery_attempts', 'SELECT')
          AND has_table_privilege(current_user, 'alert_delivery_attempts', 'INSERT')
          AND has_column_privilege(current_user, 'alert_jobs', 'status', 'UPDATE')
          AND has_column_privilege(current_user, 'alert_recipients', 'status', 'UPDATE')
          AND has_column_privilege(current_user, 'alert_delivery_attempts', 'status', 'UPDATE')
          AND has_table_privilege(current_user, 'job_dispatches', 'UPDATE')
          AND has_table_privilege(current_user, 'audit_logs', 'INSERT')
          AND has_column_privilege(current_user, 'users', 'email', 'SELECT')
          AND has_column_privilege(current_user, 'users', 'mobile_number', 'SELECT')
          AND NOT has_column_privilege(current_user, 'users', 'display_name', 'SELECT')
          AND NOT has_any_column_privilege(current_user, 'users', 'UPDATE')
          AND NOT has_table_privilege(current_user, 'alert_delivery_attempts', 'DELETE')
    """)
    )
    return GateResult(
        "alert-capabilities",
        bool(ready),
        "Restricted alert worker capabilities verified."
        if ready
        else "Restricted alert worker capabilities are unavailable.",
    )


@dataclass(frozen=True, slots=True)
class AlertReadinessGate:
    settings: object
    reconciliation: bool = False
    name: str = "alert-readiness"

    def check(self):
        try:
            if not self.settings.alert_delivery_enabled or (
                not self.reconciliation and not self.settings.alert_resolution_enabled
            ):
                return GateResult(self.name, False, "Alert delivery is disabled.")
            configured_alert_providers(
                self.settings, channels=("sms",) if self.reconciliation else ("sms", "email")
            )
            engine = create_database_engine(self.settings.database_url, statement_timeout_ms=5000)
            try:
                with engine.connect() as connection:
                    result = alert_capabilities(connection)
            finally:
                engine.dispose()
            return GateResult(
                self.name,
                result.ready,
                result.reason,
                {"provider_configuration": "valid", "provider_authentication": "unverified"},
            )
        except Exception:
            return GateResult(
                self.name, False, "Alert configuration or capabilities are unavailable."
            )


def alert_startup_gates(settings):
    return (*phase_one_startup_gates(settings), AlertReadinessGate(settings))


def reconciliation_startup_gates(settings):
    return (*phase_one_startup_gates(settings), AlertReadinessGate(settings, reconciliation=True))
