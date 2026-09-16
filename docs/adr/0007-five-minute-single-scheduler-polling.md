# Poll PHIVOLCS every five minutes with one scheduler

**Status**: accepted

The initial ingestion deployment will run one active Celery Beat scheduler with
one five-minute PHIVOLCS polling schedule. The schedule will not be duplicated
with offset or consecutive scheduler entries. Only one logical ingestion run
may be active at a time; durable dispatch and retry handling will recover work
after failures. A shorter cadence can be reconsidered later if measured source
freshness and an explicit alerting requirement justify its additional traffic
and processing cost.
