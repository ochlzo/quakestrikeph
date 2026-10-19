# Automate full application deployment after reviewed main changes

**Status**: accepted by the user on 11 October 2026.

Successful main CI deploys the Backend, Bulletin, workers, and already-enabled alert services together. This amends the separate Backend rollout in ADR 0041 and the repeat-release manual boundary in ADR 0047. Reviewed migrations and existing grants run through an explicit release job after an encrypted backup and isolated restore test pass. Container startup still never performs initialization writes.

Stop Beat, Dispatcher, consumers, reconciliation, and Backend before schema work. Serialize migration and grants with the existing host maintenance lock. Use the migration login for DDL and existing provisioning commands for restricted grants. Restore Backend before reconciliation, alert consumption, and publication. Preserve prediction replica count and whether Beat and both alert services ran. Initial alert activation, secrets, model registration, bootstrap, legacy retirement, and actual provider verification remain explicit operator actions.

Rollback images and checkout only when the database revision remains unchanged. If schema changes or cannot be verified, leave processing and Backend stopped, retain the target checkout, and require repair forward. Never automatically downgrade or restore the live database. Save private image tags atomically only after health and public checks pass; retain protected environment backups and previous images.

## Amendment: optional tools and worker health costs — 20 October 2026

Routine deployment stops pgAdmin and the separate private alert-testing services, including their Redis, before building application images.
Deployment stops the private control service before reading session state, preventing new private requests during the cleanup check.
It requires no private session or a closed/expired session whose cleanup is complete.
If that check fails, deployment restores the previously running control service and aborts before public application downtime.
It stops consumers before rechecking cleanup, then stops private Redis last.
If the final check fails, Redis stays running and private controls stay stopped for operator recovery.
After cleanup passes, deployment and rollback do not restart optional tools. Operators start them explicitly when needed.
Routine Backend composition overrides the optional test Redis URL to empty, preventing reconnect attempts while that Redis is stopped.
The saved private setting remains available for explicit manual activation.
Ordinary alert services retain the enablement rules above.

Release worker health checks run every 30 seconds through the runtime module, bypassing unrelated operator commands.
Checks retain existing dependencies and readiness requirements. Build-time Python bytecode compilation reduces repeated startup work.
The longer interval trades slower failure detection for lower CPU usage on a two-vCPU host.
