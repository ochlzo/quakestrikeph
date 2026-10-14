import { useEffect, useRef, useState } from "react";
import { estimatedProgress, isLoading, loadingListeners } from "../lib/loading";
import { toast } from "@quakestrikeph/ui/toast";
import { Button } from "@quakestrikeph/ui/button";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyContent } from "@quakestrikeph/ui/empty";
import { CircleX } from "lucide-react";

export function SectionError({ message, retry, pending = false, actionLabel = "Retry" }: {
  message: string; retry: () => void; pending?: boolean; actionLabel?: string;
}) {
  return <Empty role="alert">
    <EmptyHeader><EmptyMedia><CircleX className="size-8 text-destructive" /></EmptyMedia><EmptyTitle>{message}</EmptyTitle></EmptyHeader>
    <EmptyContent><Button variant="outline" isPending={pending} isDisabled={pending} onPress={retry}>{actionLabel}</Button></EmptyContent>
  </Empty>;
}

export function useErrorToast(message: string | null | undefined, id: string, retry?: () => void, actionLabel = "Retry") {
  const action = useRef(retry);
  action.current = retry;
  useEffect(() => {
    if (!message) { toast.close(id); return; }
    toast.add({ id, type: "error", title: message, timeout: 8000, priority: "high",
      actionProps: retry ? { children: actionLabel, onClick: () => action.current?.() } : undefined });
    return () => toast.close(id);
  }, [message, id, Boolean(retry), actionLabel]);
}

export function LoadingBar({ sessionPending }: { sessionPending: boolean }) {
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(sessionPending ? 0.08 : 0);
  const [fading, setFading] = useState(false);
  const progressRef = useRef(progress);
  const loading = busy || sessionPending;
  const [active, setActive] = useState(sessionPending);
  useEffect(() => {
    const listener = () => setBusy(isLoading());
    loadingListeners.add(listener);
    listener();
    return () => { loadingListeners.delete(listener); };
  }, []);
  useEffect(() => {
    if (loading) {
      setActive(true);
      return;
    }
    // Merge chained requests, including the 300 ms replay preparation debounce.
    const idle = window.setTimeout(() => setActive(false), 400);
    return () => window.clearTimeout(idle);
  }, [loading]);
  useEffect(() => {
    setFading(false);
    if (active) {
      const start = progressRef.current > 0 && progressRef.current < 0.94 ? progressRef.current : 0.08;
      const startedAt = performance.now();
      let frame = 0;
      const animate = (now: number) => {
        progressRef.current = estimatedProgress(now - startedAt, start);
        setProgress(progressRef.current);
        frame = window.requestAnimationFrame(animate);
      };
      progressRef.current = start;
      setProgress(start);
      frame = window.requestAnimationFrame(animate);
      return () => window.cancelAnimationFrame(frame);
    }
    progressRef.current = progressRef.current > 0 ? 1 : 0;
    setProgress(progressRef.current);
    const fade = window.setTimeout(() => setFading(true), 250);
    const hide = window.setTimeout(() => {
      progressRef.current = 0;
      setProgress(0);
    }, 450);
    return () => {
      window.clearTimeout(fade);
      window.clearTimeout(hide);
    };
  }, [active]);
  return progress > 0 ? <div className="header-loading-bar" data-loading={active || undefined} data-fading={fading || undefined}
    role="progressbar" aria-label="Loading" aria-valuetext={active ? "Loading" : "Complete"}>
    <span style={{ transform: `scaleX(${progress})` }} />
  </div> : null;
}
