"""Shared fail-closed behavior for the Phase 1 service entry points."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable

from pydantic import ValidationError

from quakestrike.application.startup import StartupGate, evaluate_startup_gates
from quakestrike.infrastructure.logging.json_logging import (
    configure_logging,
    log_event,
    log_exception_event,
)
from quakestrike.infrastructure.settings import Settings
from quakestrike.infrastructure.startup import phase_one_startup_gates

SettingsFactory = Callable[[], Settings]
GateFactory = Callable[[Settings], Iterable[StartupGate]]
RuntimeRunner = Callable[[Settings], int | None]


def run_service(
    service_name: str,
    *,
    settings_factory: SettingsFactory = Settings,
    gate_factory: GateFactory = phase_one_startup_gates,
    command: str | None = None,
    runtime: RuntimeRunner | None = None,
) -> int:
    """Validate settings and startup gates before allowing service work."""

    try:
        settings = settings_factory()
    except ValidationError as error:
        logger = configure_logging(service_name)
        log_exception_event(
            logger,
            logging.ERROR,
            "service configuration is invalid",
            event_code="configuration_invalid",
            error=error,
        )
        return 2

    logger = configure_logging(service_name, level=settings.log_level)
    log_event(
        logger,
        logging.INFO,
        "service configuration validated",
        event_code="configuration_validated",
    )

    report = evaluate_startup_gates(gate_factory(settings))
    for result in report.results:
        log_event(
            logger,
            logging.INFO if result.ready else logging.WARNING,
            "startup gate evaluated",
            event_code="startup_gate_result",
            context={
                "gate": result.name,
                "reason": result.reason,
                "status": "ready" if result.ready else "not_ready",
            },
        )

    if not report.ready:
        log_event(
            logger,
            logging.ERROR,
            "service refused to perform work because startup is not ready",
            event_code="startup_not_ready",
            context={"reason": ", ".join(report.failed_gate_names)},
        )
        return 2

    if runtime is None:
        log_event(
            logger,
            logging.ERROR,
            "service runtime is not implemented in Phase 1",
            event_code="phase_one_runtime_deferred",
            context={"reason": command or service_name},
        )
        return 2

    try:
        result = runtime(settings)
    except KeyboardInterrupt:
        log_event(
            logger,
            logging.INFO,
            "service stopped by operator",
            event_code="service_stopped",
        )
        return 0
    except Exception as error:
        log_exception_event(
            logger,
            logging.ERROR,
            "service runtime failed",
            event_code="service_runtime_failed",
            error=error,
        )
        return 1
    return 0 if result is None else result
