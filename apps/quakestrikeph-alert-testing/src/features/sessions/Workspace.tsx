import { useState, type ReactNode } from "react";
import {
  Activity, ArrowRight, Check, CheckCheck, Clock3, History, Radio, Send,
  Settings2, Square, TriangleAlert, UserCog, Users,
} from "lucide-react";
import { Button } from "@quakestrikeph/ui/button";
import { Dialog, DialogTitle, DialogDescription, DialogFooter } from "@quakestrikeph/ui/dialog";
import {
  SidebarProvider, Sidebar, SidebarInset, SidebarHeader, SidebarContent,
  SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuItem,
  SidebarMenuButton, SidebarSeparator, SidebarTrigger,
} from "@quakestrikeph/ui/sidebar";
import { Separator } from "@quakestrikeph/ui/separator";
import { useSession } from "./use-session";

type Section = "scenario" | "testers" | "history";
const sections = [
  ["scenario", "Scenario", "/", Settings2],
  ["testers", "Testers", "/testers", Users],
  ["history", "History", "/history", History],
] as const;
const pht = (time: number) => new Intl.DateTimeFormat("en-PH", {
  timeZone: "Asia/Manila", hour: "numeric", minute: "2-digit", hour12: true,
}).format(time);

// Preserve the prototype sidebar; each link opens its own Astro page.
function OperatorSidebar({ section }: { section: Section }) {
  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader>
        <a href="/" className="flex items-center gap-3 rounded-md p-2 text-foreground no-underline">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Activity className="size-5" />
          </span>
          <span className="grid text-sm">
            <strong className="font-semibold">QuakeStrike PH</strong>
            <span className="text-xs text-muted-foreground">Alert testing</span>
          </span>
        </a>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="operator-navigation">
          <SidebarGroupLabel><UserCog className="mr-2" />Operator workspace</SidebarGroupLabel>
          <SidebarMenu aria-label="Testing tool">
            {sections.map(([key, label, href, Icon]) => (
              <SidebarMenuItem key={key}>
                <SidebarMenuButton href={href} isActive={section === key} aria-current={section === key ? "page" : undefined}>
                  <Icon /><span>{label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
          <Radio className="size-3.5" />Private access · Tailscale
        </div>
        <SidebarSeparator className="mx-0" />
        <div className="flex items-center gap-3 p-2">
          <span className="flex size-8 items-center justify-center rounded-full bg-muted text-xs text-muted-foreground">OP</span>
          <span className="grid gap-0.5 text-sm">
            <strong className="font-medium">Test operator</strong>
            <span className="text-xs text-muted-foreground">Shared test session</span>
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

// The prototype session presentation uses server-confirmed state and actions.
export default function Workspace({ section, children }: { section: Section; children: ReactNode }) {
  const { session, state, pending, remaining, error, canStart, needsCleanup, refresh, act } = useSession();
  const [confirmEnd, setConfirmEnd] = useState<string | null>(null);
  const active = state === "active";
  const minutes = Math.ceil(remaining / 60000);
  const copy: Record<string, [string, string]> = {
    inactive: ["Start an alert test", "Open a shared four-hour session to prepare an alert test. Starting creates no scenario or message."],
    checking: ["Checking the session", "Waiting for the shared session. No session state is confirmed yet."],
    starting: ["Starting the session", "Waiting for the shared session. No scenario or message has been created."],
    closing: ["Ending the test", "Waiting for the server to confirm closure and temporary data cleanup."],
    ending: ["Ending the test", "The session is closed. Temporary data cleanup is in progress."],
    "cleanup-failure": ["Cleanup is incomplete", "The session stays closed. Temporary records could not all be deleted. Retry cleanup to finish."],
    ended: ["Test ended", "The session is closed. Its temporary data has been removed."],
    expired: ["Session expired", "The fixed four-hour deadline has passed. The session is closed to new work."],
    unavailable: ["Session status unavailable", error ?? "The session store did not respond. We cannot confirm the session state."],
  };
  const [title, description] = copy[state] ?? copy.inactive;

  return (
    <SidebarProvider className="tool">
      {active && <OperatorSidebar section={section} />}
      <SidebarInset className="workspace">
        <header className="shell-header">
          <div className="flex min-w-0 items-center gap-3">
            {active && <><SidebarTrigger /><Separator orientation="vertical" className="h-4 aria-[orientation=vertical]:self-center" /></>}
            <div className="session-indicator" role="status">
              <span className={`session-dot ${active ? "active" : ""}`} />
              <strong>{active ? "Test active" : ["ending", "closing"].includes(state) ? "Test ending"
                : state === "unavailable" ? "Status unavailable" : state === "starting" ? "Test starting"
                : state === "checking" ? "Checking session" : state === "cleanup-failure" ? "Cleanup incomplete" : "No active test"}</strong>
              {active && session?.expires_at_ms && <>
                <span className="expiry">Ends <time dateTime={new Date(session.expires_at_ms).toISOString()}>{pht(session.expires_at_ms)} PHT</time></span>
                <span className="remaining" aria-hidden="true">{Math.floor(minutes / 60)}h {minutes % 60}m left</span>
              </>}
            </div>
          </div>
          {active ? <Button variant="destructive" className="end-button" onPress={() => setConfirmEnd(session?.session_id ?? null)}>
            <Square size={14} fill="currentColor" />End Test
          </Button> : canStart ? <Button isPending={pending === "start"} onPress={() => void act("start")}>Start Test</Button> : null}
        </header>
        <main className="content" id="main" tabIndex={-1}>
          <div hidden={!active}>{children}</div>
          {!active && (
            <div className={`session-page ${["ended", "expired"].includes(state) ? "session-closed" : ""}`}>
              <div className={`session-symbol ${["cleanup-failure", "unavailable"].includes(state) ? "warning" : ""}`}>
                {state === "ended" ? <CheckCheck /> : ["ending", "closing", "starting", "checking", "expired"].includes(state)
                  ? <Clock3 /> : ["cleanup-failure", "unavailable"].includes(state) ? <TriangleAlert /> : <UserCog />}
              </div>
              <h1>{title}</h1><p>{description}</p>
              {state === "inactive" && <>
                <div className="session-explanation">
                  <div><Clock3 /><div><strong>Four hours, one shared deadline</strong><span>Starting again preserves the session and its fixed deadline.</span></div></div>
                  <div><Users /><div><strong>Only selected Bulletin accounts</strong><span>Tester selection is not enabled in this session slice.</span></div></div>
                  <div><Send /><div><strong>You choose when to send</strong><span>Start Test opens the session. Scenario creation and alert delivery are not enabled yet.</span></div></div>
                </div>
                <Button isPending={pending === "start"} onPress={() => void act("start")}>Start Test<ArrowRight /></Button>
              </>}
              {["starting", "checking", "closing"].includes(state) && <div className="session-progress">
                <span className="loading-line" /><p>{state === "closing" ? "Waiting for closure and cleanup…" : "Opening the shared session…"}</p>
              </div>}
              {state === "ending" && <ol className="cleanup-steps">
                <li><Check /><span>Close session</span><span className="status status-teal">Complete</span></li>
                <li><Clock3 /><span>Delete temporary records</span><span className="status">In progress</span></li>
              </ol>}
              {needsCleanup && !pending && <Button onPress={() => void act("cleanup")}>Retry cleanup<ArrowRight /></Button>}
              {state === "expired" && session?.cleanup !== "complete" && <p className="helper">Cleanup is pending. A new session remains blocked until cleanup finishes.</p>}
              {state === "unavailable" && <Button onPress={() => void refresh()}>Retry connection<ArrowRight /></Button>}
              {["ended", "expired"].includes(state) && canStart && <Button onPress={() => void act("start")}>Start a new test<ArrowRight /></Button>}
            </div>
          )}
        </main>
      </SidebarInset>
      <Dialog isOpen={confirmEnd !== null} onOpenChange={(open) => { if (!open) setConfirmEnd(null); }} className="end-dialog">
        <DialogTitle>End this test?</DialogTitle>
        <DialogDescription><p>The shared session closes for every operator. Its temporary data will be removed.</p></DialogDescription>
        <DialogFooter>
          <Button variant="outline" onPress={() => setConfirmEnd(null)}>Keep test active</Button>
          <Button variant="destructive" onPress={() => { const owner = confirmEnd; setConfirmEnd(null); if (owner) void act("end", owner); }}>End Test</Button>
        </DialogFooter>
      </Dialog>
    </SidebarProvider>
  );
}
