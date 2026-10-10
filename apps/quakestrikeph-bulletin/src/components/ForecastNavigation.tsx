import { useEffect, useRef, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

const sections = [
  { id: "main-facts", label: "Main facts" },
  { id: "activity-map", label: "Activity map" },
  { id: "forecast-details", label: "Forecast details" },
  { id: "disclaimer", label: "Disclaimer" },
];

export default function ForecastNavigation() {
  const [active, setActive] = useState("main-facts");
  const list = useRef<HTMLDivElement>(null);
  const destination = useRef<string | null>(null);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const selectSection = (id: string) => {
    destination.current = id;
    setActive(id);
    // A quiet scroll interval also covers browsers without scrollend and links already at their target.
    clearTimeout(settleTimer.current);
    settleTimer.current = setTimeout(() => { destination.current = null; }, 150);
  };

  useEffect(() => {
    let frame = 0;
    const updateSection = () => {
      if (destination.current) return;
      const visible = [...(list.current?.querySelectorAll<HTMLAnchorElement>("a") ?? [])]
        .filter(link => link.getClientRects().length > 0);
      let selected: HTMLAnchorElement | undefined = visible[0];
      visible.forEach(link => {
        if ((document.querySelector(link.hash)?.getBoundingClientRect().top ?? Infinity) <= 84) {
          selected = link;
        }
      });
      if (window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2) {
        selected = visible.at(-1);
      }
      if (selected) setActive(selected.hash.slice(1));
    };
    const onScroll = () => {
      if (destination.current) {
        clearTimeout(settleTimer.current);
        settleTimer.current = setTimeout(() => {
          destination.current = null;
          updateSection();
        }, 150);
        return;
      }
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        updateSection();
      });
    };
    const resumeTracking = () => {
      clearTimeout(settleTimer.current);
      destination.current = null;
      updateSection();
    };
    const onPointer = (event: Event) => {
      if (!list.current?.contains(event.target as Node)) resumeTracking();
    };
    const onKey = (event: KeyboardEvent) => {
      if (["PageUp", "PageDown"].includes(event.key)) {
        resumeTracking();
      } else if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", " "].includes(event.key)) {
        onPointer(event);
      }
    };
    const onHashChange = () => {
      if (location.hash.slice(1) !== destination.current) resumeTracking();
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", resumeTracking);
    window.addEventListener("wheel", resumeTracking, { passive: true });
    window.addEventListener("touchstart", onPointer, { passive: true });
    window.addEventListener("pointerdown", onPointer, { passive: true });
    window.addEventListener("keydown", onKey);
    window.addEventListener("hashchange", onHashChange);
    updateSection();
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(settleTimer.current);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", resumeTracking);
      window.removeEventListener("wheel", resumeTracking);
      window.removeEventListener("touchstart", onPointer);
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  return (
    <Tabs selectedKey={active} onSelectionChange={key => setActive(String(key))} keyboardActivation="manual">
      <TabsList ref={list} aria-label="Forecast sections">
        {sections.map(section => (
          <TabsTrigger key={section.id} id={section.id} href={`#${section.id}`}
            onPress={() => selectSection(section.id)}
            aria-current={active === section.id ? "location" : undefined}>
            {section.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
