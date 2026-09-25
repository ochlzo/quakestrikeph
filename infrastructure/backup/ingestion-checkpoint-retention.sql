WITH doomed AS MATERIALIZED (
    SELECT inputs.ctid
    FROM ingestion_run_inputs AS inputs
    JOIN ingestion_runs AS runs ON runs.run_id = inputs.run_id
    WHERE runs.trigger_type = 'scheduled'
      AND runs.status = 'succeeded'
      AND runs.finished_at < now() - interval '24 hours'
    LIMIT 5000
), removed AS (
    DELETE FROM ingestion_run_inputs AS inputs
    USING doomed
    WHERE inputs.ctid = doomed.ctid
    RETURNING 1
)
SELECT count(*) FROM removed;
