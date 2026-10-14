import { useEffect, useState } from "react";
import { CircleX, History as HistoryIcon, ExternalLink, Clock3, Check, CheckCheck, CircleHelp, Ban, Plus, ArrowRight, ChevronLeft, Mail, Smartphone } from "lucide-react";
import { Button, LinkButton } from "@quakestrikeph/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@quakestrikeph/ui/table";
import type { ScenarioResult, DeliveryStatus } from "../../../../../packages/contracts/alert-testing/delivery-v1";
import { historyRequest, resultsRequest } from "../../lib/api";
import { useWorkspace } from "../workspace/use-workspace";
import { SectionError, useErrorToast } from "../feedback";
import { scenarioStatus } from "./scenario-status";

function ScenarioBadge({ item }: { item: ScenarioResult }) {
  const status = scenarioStatus(item);
  return <span className={`status ${status.tone}`} role="status" aria-live="polite">{status.label}</span>;
}

const pht = (time: number) => new Intl.DateTimeFormat("en-PH", {
  timeZone: "Asia/Manila", dateStyle: "medium", timeStyle: "short",
}).format(time);
const icons = { pending: Clock3, skipped: Ban, accepted: Check, delivered: CheckCheck, failed: CircleX, unknown: CircleHelp };
function Outcome({ status }: { status: DeliveryStatus }) {
  const Icon = icons[status];
  return <span className={`status ${status === "delivered" ? "teal" : status === "failed" ? "red" : status === "skipped" ? "neutral" : "amber"}`}><Icon size={14} />{status[0].toUpperCase() + status.slice(1)}</span>;
}
function useDeliveryRead(results: boolean, page = 1) {
  const workspace = useWorkspace();
  const [data, setData] = useState<ScenarioResult[] | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    if (!workspace.ready) { setData(null); setError(""); }
    if (!workspace.ready) return;
    setLoading(true);
    async function read(background = false) {
      try {
        const event = window.location.pathname.split("/")[2] ?? "";
        const response = results ? await resultsRequest(workspace.owner, event, !background) : await historyRequest(workspace.owner, page, !background);
        if (cancelled) return;
        setError("");
        setData("scenarios" in response ? response.scenarios : "missing" in response ? [] : [response]);
        if ("pages" in response) setPages(response.pages);
        timer = setTimeout(() => void read(true), 3000);
      } catch {
        if (!cancelled) { setError("Could not load results."); }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void read();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [workspace.owner, workspace.ready, reload, results, page]);
  return { data, error, pages, loading, retry: () => setReload(value => value + 1) };
}

export function History() {
  const workspace = useWorkspace();
  const [page, setPage] = useState(1);
  const { data, error, pages, loading, retry } = useDeliveryRead(false, page);
  useErrorToast(data ? error : null, "history-read-error", retry);
  return <><div className="page-heading history-heading"><div><h1>Scenario history</h1><p>All scenarios share this session’s fixed deadline.</p></div><LinkButton href="/" onClick={() => workspace.newScenario()}><Plus />New scenario</LinkButton></div>
    {!data ? error ? <SectionError message={error} retry={retry} pending={loading} /> : null : !data.length ?
      <div className="empty-state history-empty-state">
        <HistoryIcon size={32} />
        <h2>No scenarios yet</h2>
        <p>Create the first scenario to review delivery outcomes and reopen its forecast.</p>
        <LinkButton href="/">Create a scenario<ArrowRight /></LinkButton>
      </div> :
      <div className="history-list">{data.map(item => <article className="history-row" key={item.event_id}>
        <strong className="history-magnitude">M{item.event.magnitude.toFixed(1)}</strong>
        <div className="history-detail"><div className="history-title"><h2>Scenario {item.event_id.slice(0, 8)}</h2><ScenarioBadge item={item} /></div><strong>{item.event.location}</strong>
          <p>Submitted {pht(item.submitted_at_ms)} PHT · {Object.values(item.counts).reduce((sum, count) => sum + count, 0) / 2} selected accounts</p>
        </div><div className="history-actions"><LinkButton variant="outline" href={`/results/${item.event_id}`}>View results<ArrowRight /></LinkButton><a href={item.forecast_url} target="_blank" rel="noopener noreferrer">Open forecast <ExternalLink size={14} /></a></div>
      </article>)}</div>}
    {pages > 1 && <nav className="history-pagination" aria-label="Scenario pages"><Button variant="outline" isDisabled={page <= 1} onPress={() => setPage(value => value - 1)}>Previous</Button><span>Page {page} of {pages}</span><Button variant="outline" isDisabled={page >= pages} onPress={() => setPage(value => value + 1)}>Next</Button></nav>}
  </>;
}

export function Results() {
  const { data, error, loading, retry } = useDeliveryRead(true);
  const item = data?.[0];
  useErrorToast(data && item ? error : null, "results-read-error", retry);
  return <><LinkButton className="back-link" variant="link" href="/history"><ChevronLeft />Scenario history</LinkButton><div className="page-heading"><div><h1>{item ? `Scenario ${item.event_id.slice(0, 8)}` : "Delivery results"}</h1><p>{item ? `Submitted ${pht(item.submitted_at_ms)} PHT · Frozen scenario and tester selection` : "Email and SMS outcomes remain independent."}</p></div>{item && <ScenarioBadge item={item} />}</div>
    {!data ? error ? <SectionError message={error} retry={retry} pending={loading} /> : null : !item ?
      <SectionError message="This scenario is no longer available." retry={() => window.location.assign("/history")} actionLabel="History" /> : <>
      <div className="result-event"><div><strong>M{item.event.magnitude.toFixed(1)}</strong><span>{item.event.location}</span></div><a href={item.forecast_url} target="_blank" rel="noopener noreferrer">Open forecast <ExternalLink size={15} /></a></div>
      <div className="results-heading"><h2>Delivery by channel</h2><span>{(item.recipients?.length ?? 0) / 2} selected accounts · {item.recipients?.length ?? 0} channel outcomes</span></div>
      <p className="section-intro">Accepted and unknown submissions are never automatically resent.</p>
      <div className="desktop-table delivery-table"><Table aria-label="Delivery outcomes"><TableHeader><TableHead isRowHeader>Account</TableHead><TableHead>Channel</TableHead><TableHead>Outcome</TableHead><TableHead>What happened</TableHead></TableHeader>
        <TableBody>{item.recipients?.map(row => <TableRow id={`${row.user_id}:${row.channel}`} textValue={`${row.name ?? "Selected account"} ${row.channel}`} key={`${row.user_id}:${row.channel}`}><TableCell><strong>{row.name ?? "Selected account"}</strong><small>{row.destination ?? "Destination checked before sending"}</small></TableCell><TableCell><span className="channel-label">{row.channel === "sms" ? <Smartphone size={16} /> : <Mail size={16} />}{row.channel === "sms" ? "SMS" : "Email"}</span></TableCell><TableCell><Outcome status={row.status} /></TableCell><TableCell>{row.reason}{row.evidence_note && <small>{row.evidence_note}</small>}</TableCell></TableRow>)}</TableBody></Table></div>
      <div className="mobile-accounts">{item.recipients?.map(row => <article className="mobile-outcome" key={`${row.user_id}:${row.channel}`}><div><strong>{row.name ?? "Selected account"} · {row.channel === "sms" ? "SMS" : "Email"}</strong><Outcome status={row.status} /></div><p>{row.reason}</p>{row.evidence_note && <p>{row.evidence_note}</p>}</article>)}</div>
      <div className="plain-notice"><CircleHelp size={18} /><p>Provider acceptance confirms submission only. Delivery reports do not prove that a tester read the message.</p></div>
    </>}
  </>;
}
