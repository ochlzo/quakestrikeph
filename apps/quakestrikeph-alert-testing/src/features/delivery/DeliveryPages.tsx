import { useEffect, useState } from "react";
import { CircleX, History as HistoryIcon, ExternalLink, Clock3, Check, CheckCheck, CircleHelp, Ban, Plus, ArrowRight, ChevronLeft, Mail, Smartphone } from "lucide-react";
import { Button, LinkButton } from "@quakestrikeph/ui/button";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent } from "@quakestrikeph/ui/empty";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@quakestrikeph/ui/table";
import type { ScenarioResult, DeliveryStatus } from "../../../../../packages/contracts/alert-testing/delivery-v1";
import { historyRequest, resultsRequest } from "../../lib/api";
import { useWorkspace } from "../workspace/use-workspace";

const pht = (time: number) => new Intl.DateTimeFormat("en-PH", {
  timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short",
}).format(time);
const icons = { pending: Clock3, skipped: Ban, accepted: Check, delivered: CheckCheck, failed: CircleX, unknown: CircleHelp };
function Outcome({ status }: { status: DeliveryStatus }) {
  const Icon = icons[status];
  return <span className={`status ${status === "delivered" ? "teal" : status === "failed" ? "red" : status === "skipped" ? "neutral" : "amber"}`}><Icon size={14} />{status[0].toUpperCase() + status.slice(1)}</span>;
}
function ReadState({ error, retry, missing = false }: { error?: string; retry: () => void; missing?: boolean }) {
  return <Empty><EmptyHeader><EmptyMedia variant="icon">{error ? <CircleX /> : <HistoryIcon />}</EmptyMedia>
    <EmptyTitle>{error ? "Results unavailable" : missing ? "Scenario unavailable" : "No scenarios yet"}</EmptyTitle>
    <EmptyDescription>{error ?? (missing ? "The scenario does not belong to the active session." : "Prepare a scenario, select testers, then use Simulate and Send.")}</EmptyDescription>
  </EmptyHeader><EmptyContent>{error ? <Button variant="outline" onPress={retry}>Try again</Button> : <a href="/">Back to scenario</a>}</EmptyContent></Empty>;
}
function useDeliveryRead(results: boolean, page = 1) {
  const workspace = useWorkspace();
  const [data, setData] = useState<ScenarioResult[] | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [pages, setPages] = useState(1);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setData(null); setError("");
    if (!workspace.ready) return;
    async function read() {
      try {
        const event = window.location.pathname.split("/")[2] ?? "";
        const response = results ? await resultsRequest(workspace.owner, event) : await historyRequest(workspace.owner, page);
        if (cancelled) return;
        setData("scenarios" in response ? response.scenarios : "missing" in response ? [] : [response]);
        if ("pages" in response) setPages(response.pages);
        timer = setTimeout(() => void read(), 3000);
      } catch {
        if (!cancelled) { setData(null); setError("The server could not load delivery results. Check the session and try again."); }
      }
    }
    void read();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [workspace.owner, workspace.ready, reload, results, page]);
  return { data, error, pages, retry: () => setReload(value => value + 1) };
}

export function History() {
  const [page, setPage] = useState(1);
  const { data, error, pages, retry } = useDeliveryRead(false, page);
  return <><div className="page-heading history-heading"><div><h1>Scenario history</h1><p>All scenarios share this session’s fixed deadline.</p></div><LinkButton href="/"><Plus />New scenario</LinkButton></div>
    {error ? <ReadState error={error} retry={retry} /> : !data ? <p role="status">Loading scenarios…</p> : !data.length ? <ReadState retry={retry} /> :
      <div className="history-list">{data.map(item => <article className="history-row" key={item.event_id}>
        <strong className="history-magnitude">M{item.event.magnitude.toFixed(1)}</strong>
        <div className="history-detail"><div className="history-title"><h2>Scenario {item.event_id.slice(0, 8)}</h2><span className="status amber">{item.queue_status === "enqueued" ? "Queued" : "Queue pending"}</span></div><strong>{item.event.location}</strong>
          <p>Submitted {pht(item.submitted_at_ms)} PHT</p>
          <p>{Object.entries(item.counts).filter(([, count]) => count > 0).map(([status, count]) => `${count} ${status}`).join(" · ")}</p>
        </div><div className="history-actions"><LinkButton variant="outline" href={`/results/${item.event_id}`}>View results<ArrowRight /></LinkButton><a href={item.forecast_url} target="_blank" rel="noopener noreferrer">Open forecast <ExternalLink size={14} /></a></div>
      </article>)}</div>}
    {pages > 1 && <nav className="history-pagination" aria-label="Scenario pages"><Button variant="outline" isDisabled={page <= 1} onPress={() => setPage(value => value - 1)}>Previous</Button><span>Page {page} of {pages}</span><Button variant="outline" isDisabled={page >= pages} onPress={() => setPage(value => value + 1)}>Next</Button></nav>}
  </>;
}

export function Results() {
  const { data, error, retry } = useDeliveryRead(true);
  const item = data?.[0];
  return <><LinkButton className="back-link" variant="link" href="/history"><ChevronLeft />Scenario history</LinkButton><div className="page-heading"><div><h1>{item ? `Scenario ${item.event_id.slice(0, 8)}` : "Delivery results"}</h1><p>{item ? `Submitted ${pht(item.submitted_at_ms)} PHT · Frozen scenario and tester selection` : "Email and SMS outcomes remain independent."}</p></div>{item && <span className="status amber">{item.queue_status === "enqueued" ? "Queued" : "Queue pending"}</span>}</div>
    {error ? <ReadState error={error} retry={retry} /> : !data ? <p role="status">Loading results…</p> : !item ? <ReadState missing retry={retry} /> : <>
      <div className="result-event"><div><strong>M{item.event.magnitude.toFixed(1)}</strong><span>{item.event.location}</span></div><a href={item.forecast_url} target="_blank" rel="noopener noreferrer">Open forecast <ExternalLink size={15} /></a></div>
      <div className="results-heading"><h2>Delivery by channel</h2><span>{(item.recipients?.length ?? 0) / 2} selected accounts · {item.recipients?.length ?? 0} channel outcomes</span></div>
      <p className="section-intro">Accepted and unknown submissions are never automatically resent.</p>
      <div className="desktop-table delivery-table"><Table aria-label="Delivery outcomes"><TableHeader><TableHead isRowHeader>Account</TableHead><TableHead>Channel</TableHead><TableHead>Outcome</TableHead><TableHead>What happened</TableHead></TableHeader>
        <TableBody>{item.recipients?.map(row => <TableRow id={`${row.user_id}:${row.channel}`} textValue={`${row.name ?? "Selected account"} ${row.channel}`} key={`${row.user_id}:${row.channel}`}><TableCell><strong>{row.name ?? "Selected account"}</strong><small>{row.destination ?? "Destination checked before sending"}</small></TableCell><TableCell><span className="channel-label">{row.channel === "sms" ? <Smartphone size={16} /> : <Mail size={16} />}{row.channel === "sms" ? "SMS" : "Email"}</span></TableCell><TableCell><Outcome status={row.status} /></TableCell><TableCell>{row.reason}</TableCell></TableRow>)}</TableBody></Table></div>
      <div className="mobile-accounts">{item.recipients?.map(row => <article className="mobile-outcome" key={`${row.user_id}:${row.channel}`}><div><strong>{row.name ?? "Selected account"} · {row.channel === "sms" ? "SMS" : "Email"}</strong><Outcome status={row.status} /></div><p>{row.reason}</p></article>)}</div>
      <div className="plain-notice"><CircleHelp size={18} /><p>Provider acceptance confirms submission only. Delivery reports do not prove that a tester read the message.</p></div>
    </>}
  </>;
}
