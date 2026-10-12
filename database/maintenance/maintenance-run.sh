#!/usr/bin/env bash
# Sourced by host jobs after taking their shared lock. PostgreSQL failures leave
# a journal warning; the maintenance job itself can still protect its data.

maintenance_psql() {
  "${compose[@]}" exec -T postgres psql -X -qAt -v ON_ERROR_STOP=1 \
    -U quakestrike_maintenance -d "$maintenance_database_name" "$@"
}

maintenance_record_failure() {
  if "${compose[@]}" exec -T postgres pg_isready -q -d "$maintenance_database_name"; then
    maintenance_logging_failed=1
    echo 'PostgreSQL is ready but the maintenance record failed' >&2
  else
    echo 'PostgreSQL maintenance record unavailable; check this systemd journal' >&2
  fi
}

maintenance_begin() {
  local operation_type=$1 target=$2 related_backup_run_id=${3:-} candidate
  candidate=$(< /proc/sys/kernel/random/uuid)
  if maintenance_psql -v run_id="$candidate" -v operation_type="$operation_type" \
      -v target="$target" -v related_backup_run_id="$related_backup_run_id" <<'SQL'
UPDATE maintenance_runs SET status = 'abandoned',
  finished_at = GREATEST(now(), started_at),
  error_message = 'Interrupted before the next maintenance attempt'
WHERE status = 'running';
INSERT INTO maintenance_runs
  (maintenance_run_id, operation_type, target, correlation_id, related_backup_run_id)
VALUES (:'run_id'::uuid, :'operation_type', :'target', :'run_id'::uuid,
  NULLIF(:'related_backup_run_id', '')::uuid);
SQL
  then
    active_run_id=$candidate
  else
    active_run_id=
    maintenance_record_failure
  fi
}

maintenance_end() {
  local status=$1 artifact_reference=${2:-} artifact_checksum=${3:-}
  local related_backup_run_id=${4:-} verification_summary=${5:-} error_message=${6:-}
  local affected_row_count=${7:-}
  if [[ -z ${active_run_id:-} ]]; then
    echo "Maintenance $status; no PostgreSQL record (see systemd journal)" >&2
    return 0
  fi
  if ! maintenance_psql -v run_id="$active_run_id" -v status="$status" \
      -v artifact_reference="$artifact_reference" -v artifact_checksum="$artifact_checksum" \
      -v related_backup_run_id="$related_backup_run_id" \
      -v verification_summary="$verification_summary" -v error_message="$error_message" \
      -v affected_row_count="$affected_row_count" <<'SQL'
UPDATE maintenance_runs SET
  status = :'status'::maintenance_run_status,
  finished_at = GREATEST(now(), started_at),
  artifact_reference = NULLIF(:'artifact_reference', ''),
  artifact_checksum = NULLIF(:'artifact_checksum', ''),
  related_backup_run_id = COALESCE(NULLIF(:'related_backup_run_id', '')::uuid, related_backup_run_id),
  affected_row_count = NULLIF(:'affected_row_count', '')::bigint,
  verification_summary = NULLIF(:'verification_summary', ''),
  error_message = NULLIF(:'error_message', '')
WHERE maintenance_run_id = :'run_id'::uuid AND status = 'running';
SQL
  then
    maintenance_record_failure
  fi
  active_run_id=
}
