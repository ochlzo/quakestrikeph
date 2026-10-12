import { useEffect, useRef, useState } from "react";
import MapPanel from "../../components/MapPanel";
import type { Earthquake, EarthquakeDetail } from "../../lib/events";
import { initReplayTimeline } from "./timeline";
import { Toaster } from "../../components/ui/toast";

export default function ReplayMap({
  event,
}: {
  event: EarthquakeDetail;
}) {
  const anchor = useRef<HTMLSpanElement>(null);
  const [events, setEvents] = useState<Earthquake[]>([event]);
  const [focusRequest, setFocusRequest] = useState(0);
  useEffect(() => {
    const root = anchor.current?.closest<HTMLElement>("[data-forecast-replay]");
    if (!root) return;
    return initReplayTimeline(root, event, (observations) => {
      setEvents([event, ...observations]);
    });
  }, [event]);
  return (
    <>
      <span ref={anchor} hidden />
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
