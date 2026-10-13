import { Router } from 'express';
import { searchEarthquakes } from '../../../application/information/earthquakes.js';
import type { EarthquakeReader } from '../../../ports/earthquakeReader.js';
import type { SyntheticScenarioReader } from '../../../ports/syntheticScenarioReader.js';
import { readSyntheticScenario, searchSyntheticObservations } from '../../../application/information/syntheticScenarios.js';
import { detail, listItem } from '../responses.js';
import { encodeCursor, InvalidRequest, parseSearchRequest, validEventId } from '../searchRequest.js';

export function earthquakeRoutes(reader: EarthquakeReader, now: () => Date, synthetic?: SyntheticScenarioReader): Router {
  const router = Router();

  router.post('/search', async (req, res) => {
    const criteria = parseSearchRequest(req.body);
    const page = await searchEarthquakes(reader, criteria);
    const fetchedAt = now();
    res.json({
      items: page.items.map((item) => listItem(item, fetchedAt)),
      nextCursor: page.nextCursor ? encodeCursor(page.nextCursor) : null,
      hasMore: page.hasMore,
      fetchedAt: fetchedAt.toISOString(),
    });
  });

  router.post('/:eventId/observations', async (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    if (req.query.test !== 'true') throw new InvalidRequest('Synthetic observations require test=true');
    const eventId = req.params.eventId;
    if (typeof eventId !== 'string' || !validEventId(eventId)) throw new InvalidRequest('eventId must be a UUID');
    const criteria = parseSearchRequest(req.body);
    if (!criteria.dateFrom || !criteria.dateTo || criteria.location || criteria.magnitudeRanges.length ||
        Date.parse(criteria.dateTo) - Date.parse(criteria.dateFrom) > 86400000) {
      throw new InvalidRequest('Observations require a time window of at most 24 hours, without location or magnitude filters');
    }
    const page = await searchSyntheticObservations(synthetic, eventId.toLowerCase(), criteria);
    if (!page) {
      res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Earthquake not found' } });
      return;
    }
    const fetchedAt = now();
    res.json({ items: page.items.map(item => listItem(item, fetchedAt)),
      nextCursor: page.nextCursor ? encodeCursor(page.nextCursor) : null, hasMore: page.hasMore,
      fetchedAt: fetchedAt.toISOString() });
  });

  router.get('/:eventId', async (req, res) => {
    const eventId = req.params.eventId;
    if (typeof eventId !== 'string' || !validEventId(eventId)) throw new InvalidRequest('eventId must be a UUID');
    if (req.query.test !== undefined && typeof req.query.test !== 'string') throw new InvalidRequest('test must be a single value');
    const testMode = req.query.test === 'true';
    if (testMode) res.setHeader('Cache-Control', 'no-store');
    const scenario = testMode ? await readSyntheticScenario(synthetic, eventId.toLowerCase()) : null;
    const earthquake = testMode ? scenario?.event : await reader.findById(eventId);
    if (!earthquake) {
      res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Earthquake not found' } });
      return;
    }
    const fetchedAt = now();
    res.json({ item: detail(earthquake, fetchedAt), fetchedAt: fetchedAt.toISOString(),
      ...(scenario ? { expiresAt: new Date(scenario.expiresAtMs).toISOString() } : {}) });
  });

  return router;
}
