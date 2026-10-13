export const eventId = '11111111-1111-4111-8111-111111111111';
export const sessionId = '22222222-2222-4222-8222-222222222222';

export function submittedFixture(deadline: number, preparedAt = Date.now() - 60000) {
  const start = preparedAt - 86400000;
  return {
    version: 1, submitted: true, submitted_at_ms: preparedAt + 1,
    event_revision_id: '33333333-3333-4333-8333-333333333333',
    forecast_id: '44444444-4444-4444-8444-444444444444',
    model_release_id: 'a7f2286b-13a2-4708-a04d-4139281a4e1f',
    testers: [{ account: 'private-account', email: 'private@example.invalid', latitude: 8 }],
    deliveries: { phone: 'private-phone', result: 'private-delivery' },
    scenario: {
      version: 1, session_id: sessionId, event_id: eventId, prepared_at_ms: preparedAt, expires_at_ms: deadline,
      event: { event_time_ms: start, magnitude: 4, depth_km: 12, latitude: 7, longitude: 125, location: 'Davao' },
      forecast: { window_start_ms: start, window_end_ms: start + 86400000,
        p1: .8, p4: .2, p5: .1, count: 3.5, radius_km: 25, quantiles: [1, 2, 4] },
      replay: { local: 2, background: 1, spread: 40, spillover: 1 },
      observations: ['inside', 'spillover', 'background'].map((kind, index) => ({
        event_id: `55555555-5555-4555-8555-55555555555${index}`,
        event_time_ms: start + 1000 + index * 1000, latitude: 7 + index * 10, longitude: 125,
        magnitude: 2 + index, depth_km: 10, location_description: `Saved ${kind}`,
        kind, distance_km: index * 1000, bearing_radians: 0,
      })),
    },
  };
}
