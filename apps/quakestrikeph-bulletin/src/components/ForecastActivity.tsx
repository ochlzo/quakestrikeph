import { useEffect, useState } from "react";
import MapPanel from "./MapPanel";
import type { Earthquake, EarthquakeDetail } from "../lib/events";
import { initForecastActivity } from "../lib/forecast-activity";
import { Toaster } from "./ui/toast";

export default function ForecastActivity({
  event,
}: {
  event: EarthquakeDetail;
}) {
  const [events, setEvents] = useState<Earthquake[]>([event]);
  const [focusRequest, setFocusRequest] = useState(0);
  useEffect(
    () =>
      initForecastActivity(event, (observations) => {
        setEvents([event, ...observations]);
      }),
    [event],
  );
  return (
    <>
      <Toaster />
      <MapPanel
        events={events}
        selectedId={event.eventId}
        focusRequest={focusRequest}
        forecast={event.forecast}
        forecastStatus="ready"
        showForecastOverview={false}
        forecastAnchor={event}
        onSelect={() => {
          setFocusRequest((value) => value + 1);
        }}
      />
    </>
  );
}
