import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import test from 'node:test';
import { Pool } from 'pg';
import { searchEarthquakes } from '../../src/application/information/earthquakes.js';
import { PostgresEarthquakeReader } from '../../src/infrastructure/postgres/earthquakeQueries.js';

const url = process.env.TEST_DATABASE_URL;
const backendUrl = process.env.TEST_BACKEND_DATABASE_URL;

test('search and detail use latest revisions and current successful forecasts', { skip: !url || !backendUrl }, async () => {
  if (!url || !backendUrl) return;
  if (new URL(url).pathname !== '/quakestrike_test') throw new Error('Integration test requires quakestrike_test');
  const pool = new Pool({ connectionString: url });
  const backendPool = new Pool({ connectionString: backendUrl });
  const runId = randomUUID();
  const eventA = randomUUID(), eventB = randomUUID(), eventC = randomUUID(), duplicate = randomUUID();
  const oldRevisionA = randomUUID(), revisionA = randomUUID(), revisionB = randomUUID();
  const oldRevisionC = randomUUID(), revisionC = randomUUID(), duplicateRevision = randomUUID();
  const releaseId = randomUUID(), otherReleaseId = randomUUID();
  const oldJob = randomUUID(), selectedJob = randomUUID(), failedJob = randomUUID(), staleJob = randomUUID();
  const selectedForecast = randomUUID();
  const snapshot = {
    anchor_magnitude: 4.2, anchor_depth_km: 12, anchor_latitude: 7.1,
    anchor_longitude: 125.6, anchor_time_is_minute_precision: 0,
    catalog_m1_plus_count_past_1h: 0, catalog_m1_plus_count_past_24h: 0,
    catalog_m1_plus_count_past_7d: 0, local_m1_plus_count_past_24h_within_50km: 0,
    local_m1_plus_count_past_24h_within_100km: 0,
  };
  try {
    await pool.query(`INSERT INTO ingestion_runs (run_id, trigger_type, correlation_id)
      VALUES ($1, 'manual', $2)`, [runId, randomUUID()]);
    for (const id of [eventA, eventB, eventC, duplicate]) {
      await pool.query(`INSERT INTO earthquake_events (event_id, first_seen_run_id, last_seen_run_id)
        VALUES ($1, $2, $2)`, [id, runId]);
    }
    await pool.query('UPDATE earthquake_events SET superseded_by_event_id = $1 WHERE event_id = $2', [eventA, duplicate]);
    const revisions = [
      [oldRevisionA, eventA, 1, '2026-09-24T00:00:00Z', 3.9, 'Old Davao text'],
      [revisionA, eventA, 2, '2026-09-27T00:00:00Z', 4.0, 'Near Davao City'],
      [revisionB, eventB, 1, '2026-09-26T00:00:00Z', 2.9, 'Davao del Sur'],
      [oldRevisionC, eventC, 1, '2026-09-24T12:00:00Z', 5.0, 'Old Cebu text'],
      [revisionC, eventC, 2, '2026-09-25T00:00:00Z', 5.1, 'Cebu'],
      [duplicateRevision, duplicate, 1, '2026-09-28T00:00:00Z', 2.0, 'Davao duplicate'],
    ] as const;
    for (const [revisionId, eventId, number, eventTime, magnitude, location] of revisions) {
      await pool.query(`INSERT INTO earthquake_event_revisions
        (event_revision_id, event_id, revision_number, ingestion_run_id, source_event_group_id,
         source_url, source_time_precision, event_time, latitude, longitude, depth_km, magnitude, location_description,
         prediction_skip_reason)
        VALUES ($1, $2, $3, $4, $5, 'https://example.org/bulletin', 'second', $6, 7.1, 125.6, 12, $7, $8, $9)`,
      [revisionId, eventId, number, runId, `GROUP_${revisionId.slice(0, 8).toUpperCase()}`, eventTime, magnitude, location,
        eventId === eventA || eventId === eventB ? 'history_starts_after_required_window' : null]);
    }
    for (const [id, label] of [[releaseId, 'selected'], [otherReleaseId, 'other']]) {
      await pool.query(`INSERT INTO model_releases
        (model_release_id, version_label, artifact_manifest_uri, artifact_manifest_hash,
         input_schema_version, output_schema_version)
        VALUES ($1, $2, 'test://manifest', $3, 'input.v1', 'output.v2')`,
      [id, label, 'a'.repeat(64)]);
    }
    const jobs = [
      [oldJob, revisionA, releaseId, '2026-09-27T01:00:00Z', 'succeeded', 'a'],
      [selectedJob, revisionA, releaseId, '2026-09-27T02:00:00Z', 'succeeded', 'b'],
      [failedJob, revisionA, releaseId, '2026-09-27T03:00:00Z', 'failed', 'c'],
      [staleJob, oldRevisionC, releaseId, '2026-09-24T13:00:00Z', 'succeeded', 'd'],
    ] as const;
    for (const [jobId, revisionId, modelId, requestedAt, status, hash] of jobs) {
      await pool.query(`INSERT INTO prediction_jobs
        (job_id, event_revision_id, model_release_id, input_snapshot_hash, input_snapshot_json,
         idempotency_key, status, requested_at, completed_at, correlation_id)
        VALUES ($1, $2, $3, quakestrike_prediction_input_snapshot_sha256($4::jsonb),
          $4::jsonb, $5, $6, $7, $7, $8)`,
      [jobId, revisionId, modelId,
        JSON.stringify({ ...snapshot, catalog_m1_plus_count_past_1h: hash.charCodeAt(0) }),
        `${jobId}-${hash}`, status, requestedAt, randomUUID()]);
    }
    for (const [forecastId, jobId, start, m4] of [
      [randomUUID(), oldJob, '2026-09-27T00:00:00Z', 0.1],
      [selectedForecast, selectedJob, '2026-09-27T00:00:00Z', 0.2],
      [randomUUID(), staleJob, '2026-09-24T12:00:00Z', 0.3],
    ] as const) {
      await pool.query(`INSERT INTO forecasts
        (forecast_id, job_id, window_start, window_end, probability_m1_plus_24h,
         expected_m1_plus_count_24h, probability_m4_plus_24h, probability_m5_plus_24h)
        VALUES ($1, $2, $3, $3::timestamptz + interval '24 hours', 0.7, 1.2, $4, 0.05)`,
      [forecastId, jobId, start, m4]);
    }
    const reader = new PostgresEarthquakeReader(backendPool, releaseId);
    await reader.check();
    await assert.rejects(() => backendPool.query('INSERT INTO ingestion_runs (run_id) VALUES ($1)', [randomUUID()]),
      (error: unknown) => !!error && typeof error === 'object' && 'code' in error &&
        ['25006', '42501'].includes(String(error.code)));
    await assert.rejects(() => backendPool.query('SELECT * FROM audit_logs'), { code: '42501' });
    const criteria = { magnitudeRanges: [{ below: 3 }, { from: 4, below: 5 }],
      location: 'dAVao', limit: 1 };
    const first = await searchEarthquakes(reader, criteria);
    assert.deepEqual(first.items.map((item) => item.eventId), [eventA]);
    assert.equal(first.items[0]?.forecast?.forecastId, selectedForecast);
    assert.equal(first.hasMore, true);
    const second = await searchEarthquakes(reader, { ...criteria, cursor: first.nextCursor! });
    assert.deepEqual(second.items.map((item) => item.eventId), [eventB]);
    assert.equal(second.items[0]?.forecast, null);
    assert.equal(second.hasMore, false);
    assert.equal((await reader.findById(eventC))?.forecast, null);
    assert.deepEqual((await reader.findById(eventA))?.forecastAvailability,
      { status: 'available', reason: null }, 'A recovered forecast outranks the skip reason and a later failed job');
    assert.deepEqual((await reader.findById(eventB))?.forecastAvailability,
      { status: 'unavailable', reason: 'insufficient_history' });
    assert.deepEqual((await reader.findById(eventC))?.forecastAvailability,
      { status: 'unavailable', reason: 'unknown' }, 'An older revision does not determine availability');
    assert.equal(await reader.findById(duplicate), null);
    const all = await reader.search({ magnitudeRanges: [], limit: 25 });
    assert.deepEqual(all.map((item) => item.eventId), [eventA, eventB, eventC]);
    const literal = await reader.search({ magnitudeRanges: [], location: 'Da_ao', limit: 25 });
    assert.deepEqual(literal, []);
    const dated = await reader.search({ magnitudeRanges: [],
      dateFrom: '2026-09-26T00:00:00Z', dateTo: '2026-09-27T00:00:00Z', limit: 25 });
    assert.deepEqual(dated.map((item) => item.eventId), [eventB]);
    await assert.rejects(() => backendPool.query('SELECT last_error_message FROM prediction_jobs'), { code: '42501' });
    for (const [index, status] of ['pending', 'running', 'retry_wait', 'failed', 'cancelled', 'succeeded'].entries()) {
      const jobId = randomUUID();
      await pool.query(`INSERT INTO prediction_jobs
        (job_id, event_revision_id, model_release_id, input_snapshot_hash, input_snapshot_json,
         idempotency_key, status, requested_at, completed_at, next_attempt_at, correlation_id)
        VALUES ($1, $2, $3, quakestrike_prediction_input_snapshot_sha256($4::jsonb), $4::jsonb,
          $5, $6, $7, $8, $9, $10)`,
      [jobId, revisionB, releaseId,
        JSON.stringify({ ...snapshot, catalog_m1_plus_count_past_1h: index }), jobId, status,
        new Date(Date.UTC(2026, 8, 26, index + 1)),
        ['failed', 'cancelled', 'succeeded'].includes(status) ? new Date('2026-09-27T00:00:00Z') : null,
        status === 'retry_wait' ? new Date('2026-09-27T00:00:00Z') : null, randomUUID()]);
      assert.deepEqual((await reader.findById(eventB))?.forecastAvailability,
        ['pending', 'running', 'retry_wait'].includes(status) ? { status: 'processing', reason: null }
          : status === 'failed' ? { status: 'failed', reason: null } : { status: 'unavailable', reason: 'unknown' });
    }
    // A job for another model release must not change the selected release's public status.
    const otherJob = randomUUID();
    await pool.query(`INSERT INTO prediction_jobs
      (job_id, event_revision_id, model_release_id, input_snapshot_hash, input_snapshot_json,
       idempotency_key, correlation_id)
      VALUES ($1::uuid, $2, $3, quakestrike_prediction_input_snapshot_sha256($4::jsonb), $4::jsonb, $1::text, $5)`,
    [otherJob, revisionC, otherReleaseId, JSON.stringify(snapshot), randomUUID()]);
    assert.deepEqual((await reader.findById(eventC))?.forecastAvailability,
      { status: 'unavailable', reason: 'unknown' });
  } finally {
    await pool.query(`TRUNCATE maintenance_runs, source_catalog_evidence, ingestion_run_inputs,
      earthquake_bulletin_event_identities, audit_logs, job_dispatches, prediction_jobs,
      model_releases, earthquake_event_revisions, earthquake_events, ingestion_runs CASCADE`);
    await pool.end();
    await backendPool.end();
  }
});
