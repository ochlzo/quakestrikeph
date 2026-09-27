import { Router } from 'express';
import { searchEarthquakes } from '../../../application/information/earthquakes.js';
import type { EarthquakeReader } from '../../../ports/earthquakeReader.js';
import { detail, listItem } from '../responses.js';
import { encodeCursor, InvalidRequest, parseSearchRequest, validEventId } from '../searchRequest.js';

export function earthquakeRoutes(reader: EarthquakeReader, now: () => Date): Router {
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

  router.get('/:eventId', async (req, res) => {
    const eventId = req.params.eventId;
    if (typeof eventId !== 'string' || !validEventId(eventId)) throw new InvalidRequest('eventId must be a UUID');
    const earthquake = await reader.findById(eventId);
    if (!earthquake) {
      res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Earthquake not found' } });
      return;
    }
    const fetchedAt = now();
    res.json({ item: detail(earthquake, fetchedAt), fetchedAt: fetchedAt.toISOString() });
  });

  return router;
}
