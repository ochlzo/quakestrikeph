import { Logo } from "@quakestrikeph/ui/logo";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowRight,
  Check,
  CheckCheck,
  Clock3,
  History,
  Radio,
  Send,
  Settings2,
  Square,
  TriangleAlert,
  UserCog,
  Users,
} from "lucide-react";
import { Button } from "@quakestrikeph/ui/button";
import {
  Dialog,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@quakestrikeph/ui/dialog";
import {
  SidebarProvider,
  Sidebar,
  SidebarInset,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarSeparator,
  SidebarTrigger,
} from "@quakestrikeph/ui/sidebar";
import { Separator } from "@quakestrikeph/ui/separator";
import { useSession } from "./use-session";
import { Toaster, toast } from "@quakestrikeph/ui/toast";
import { LoadingBar, useErrorToast } from "../feedback";
import { useWorkspace } from "../workspace/use-workspace";

type Section = "scenario" | "testers" | "history";
const sections = [
  ["scenario", "Scenario", "/", Settings2],
  ["testers", "Testers", "/testers", Users],
  ["history", "History", "/history", History],
] as const;
const pht = (time: number) =>
  new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(time);

// Preserve the prototype sidebar; each link opens its own Astro page.
function OperatorSidebar({ section }: { section: Section }) {
  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader>
        <Logo subtitle="Alert testing" className="p-2" />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="operator-navigation">
          <SidebarGroupLabel>
            <UserCog className="mr-2" />
            Operator workspace
          </SidebarGroupLabel>
          <SidebarMenu aria-label="Testing tool">
            {sections.map(([key, label, href, Icon]) => (
              <SidebarMenuItem key={key}>
                <SidebarMenuButton
                  href={href}
                  isActive={section === key}
                  aria-current={section === key ? "page" : undefined}
                >
                  <Icon />
                  <span>{label}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <div className="flex items-center gap-2 px-2 py-2 text-xs text-muted-foreground">
          <Radio className="size-3.5" />
          Private access · Tailscale
        </div>
        <SidebarSeparator className="mx-0" />
        <div className="flex items-center gap-3 p-2">
          <span className="flex size-8 items-center justify-center rounded-full bg-muted text-xs text-muted-foreground">
            OP
          </span>
          <span className="grid gap-0.5 text-sm">
            <strong className="font-medium">Test operator</strong>
            <span className="text-xs text-muted-foreground">
              Shared test session
            </span>
          </span>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}

// The prototype session presentation uses server-confirmed state and actions.
export default function Workspace({
  section,
  children,
}: {
  section: Section;
  children: ReactNode;
}) {
  const {
    session,
    state,
    pending,
    remaining,
    callRemaining,
    error,
    canStart,
    needsCleanup,
    refresh,
    act,
  } = useSession();
  const workspace = useWorkspace();
  const [toastContainer, setToastContainer] = useState<HTMLDivElement | null>(null);
  useErrorToast(workspace.restoreError || workspace.saveError, "workspace-persistence", workspace.retryPersistence);
  const cleanupFailed = state === "cleanup-failure";
  const originBlocked = error === "Open the private testing URL.";
  useErrorToast(error ?? (cleanupFailed ? "Could not finish cleanup." : null), "session-error",
    originBlocked ? undefined : () => { if (cleanupFailed) void act("cleanup"); else void refresh(); });
  const previousState = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (previousState.current && previousState.current !== state) {
      if (["ended", "expired"].includes(state)) toast.add({ id: "session-closed", type: "info", title: state === "ended" ? "Test ended." : "Test session expired.", timeout: 8000 });
      if (state === "active" && ["starting", "inactive"].includes(previousState.current)) toast.add({ id: "session-started", type: "success", title: "Test started.", timeout: 5000 });
    }
    previousState.current = state;
  }, [state]);
  useEffect(() => {
    if (session && state !== "unavailable")
      window.dispatchEvent(
        new CustomEvent("alert-testing-session", {
          detail: {
            ...session,
            status: state === "expired" ? "expired" : session.status,
          },
        }),
      );
  }, [session, state]);
  const [confirmEnd, setConfirmEnd] = useState<string | null>(null);
  const active = state === "active";
  const checking = state === "checking" || state === "starting" || state === "closing";
  const showWorkspace = active || checking;
  const minutes = Math.ceil(remaining / 60000);
  const waiting = session?.closure_phase === "waiting";
  const cleanupProgress =
    !active &&
    !["none", "complete", "failed", undefined].includes(session?.closure_phase);
  const copy: Record<string, [string, string]> = {
    inactive: [
      "Start an alert test",
      "Open a shared four-hour session to prepare an alert test.",
    ],
    starting: [
      "Starting the session",
      "Waiting for the shared session. No scenario or message has been created.",
    ],
    closing: [
      "Ending the test",
      "Waiting for the server to confirm closure and temporary data cleanup.",
    ],
    ending: [
      "Ending the test",
      "The session is closed. Scenario links are invalid, and pending sends have stopped.",
    ],
    "cleanup-failure": [
      "Cleanup is incomplete",
      "The session stays closed. Temporary records could not all be deleted. Retry cleanup to finish.",
    ],
    ended: [
      "Test ended",
      "Temporary scenarios and delivery outcomes are no longer available. Earlier forecast links are invalid.",
    ],
    expired: [
      "Session expired",
      "The fixed four-hour deadline has passed. Scenario links are invalid, and new sends are blocked.",
    ],
    unavailable: [
      "Session status unavailable",
      error ??
        "The session store did not respond. We cannot confirm the session state.",
    ],
  };
  const [title, description] = copy[state] ?? copy.inactive;

  return (
    <SidebarProvider className="tool">
      {showWorkspace && <OperatorSidebar section={section} />}
      <SidebarInset className="workspace">
        <header className="shell-header">
          <div className="flex min-w-0 items-center gap-3">
            {showWorkspace && (
              <>
                <SidebarTrigger />
                <Separator
                  orientation="vertical"
                  className="h-4 aria-[orientation=vertical]:self-center"
                />
              </>
            )}
            <div className="session-indicator" role="status">
              <span className={`session-dot ${active ? "active" : ""}`} />
              {!checking && <>
              <strong>
                {active
                  ? "Test active"
                  : ["ending", "closing"].includes(state)
                    ? "Test ending"
                    : state === "unavailable"
                      ? "Status unavailable"
                      : state === "cleanup-failure"
                            ? "Cleanup incomplete"
                            : "No active test"}
              </strong>
              </>}
              {active && session?.expires_at_ms && (
                <>
                  <span className="expiry">
                    Ends{" "}
                    <time
                      dateTime={new Date(session.expires_at_ms).toISOString()}
                    >
                      {pht(session.expires_at_ms)} PHT
                    </time>
                  </span>
                  <span className="remaining" aria-hidden="true">
                    {Math.floor(minutes / 60)}h {minutes % 60}m left
                  </span>
                </>
              )}
            </div>
          </div>
          {active ? (
            <Button
              variant="destructive"
              className="end-button"
              onPress={() => setConfirmEnd(session?.session_id ?? null)}
            >
              <Square size={14} fill="currentColor" />
              End Test
            </Button>
          ) : canStart ? (
            <Button
              isPending={pending === "start"}
              onPress={() => void act("start")}
            >
              Start Test
            </Button>
          ) : null}
          <LoadingBar sessionPending={checking} />
        </header>
        <main className="content" id="main" tabIndex={-1}>
          <div hidden={!showWorkspace} aria-busy={checking} inert={checking}>{children}</div>
          {!showWorkspace && (
            <div
              className={`session-page ${["ended", "expired"].includes(state) ? "session-closed" : ""}`}
            >
              <div
                className={`session-symbol ${["cleanup-failure", "unavailable"].includes(state) ? "warning" : ""}`}
              >
                {state === "ended" ? (
                  <CheckCheck />
                ) : [
                    "ending",
                    "closing",
                    "starting",
                    "checking",
                    "expired",
                  ].includes(state) ? (
                  <Clock3 />
                ) : ["cleanup-failure", "unavailable"].includes(state) ? (
                  <TriangleAlert />
                ) : (
                  <UserCog />
                )}
              </div>
              <h1>{title}</h1>
              {!["unavailable", "cleanup-failure"].includes(state) && <p>{description}</p>}
              {state === "inactive" && (
                <>
                  <div className="session-explanation">
                    <div>
                      <Clock3 />
                      <div>
                        <strong>Four hours, one shared deadline</strong>
                        <span>
                          Starting again preserves the session and its fixed
                          deadline.
                        </span>
                      </div>
                    </div>
                    <div>
                      <Users />
                      <div>
                        <strong>Only selected Bulletin accounts</strong>
                        <span>
                          Choose testers without changing their saved alert
                          preferences.
                        </span>
                      </div>
                    </div>
                    <div>
                      <Send />
                      <div>
                        <strong>You choose when to send</strong>
                        <span>
                          Start Test opens the session. Simulate and Send queues
                          an alert.
                        </span>
                      </div>
                    </div>
                  </div>
                  <Button
                    isPending={pending === "start"}
                    onPress={() => void act("start")}
                  >
                    Start Test
                    <ArrowRight />
                  </Button>
                </>
              )}
              {cleanupProgress &&
                !["unavailable", "closing"].includes(state) && (
                  <>
                    <ol className="cleanup-steps" aria-label="Session cleanup">
                      <li>
                        <Check />
                        <span>Close session and invalidate links</span>
                        <span className="status status-teal">Complete</span>
                      </li>
                      <li>
                        <Check />
                        <span>Stop pending sends</span>
                        <span className="status status-teal">Complete</span>
                      </li>
                      <li>
                        {waiting ? <Clock3 /> : <Check />}
                        <span>Wait for authorized provider calls</span>
                        <span
                          className={`status ${waiting ? "status-amber" : "status-teal"}`}
                        >
                          {waiting ? "Waiting" : "Complete"}
                        </span>
                      </li>
                      <li>
                        {waiting ? <Square /> : <Clock3 />}
                        <span>Delete temporary records</span>
                        <span className="status">
                          {waiting ? "Waiting" : "In progress"}
                        </span>
                      </li>
                    </ol>
                    <p className="helper">
                      {waiting
                        ? callRemaining > 0
                          ? `The authorized-call grace period ends within ${Math.ceil(callRemaining / 1000)} seconds. `
                          : "The server is checking the authorized-call deadline. "
                        : "Temporary data cleanup is in progress. "}
                      Submitted messages cannot be recalled.
                    </p>
                  </>
                )}
              {needsCleanup && !pending && (
                <Button onPress={() => void act("cleanup")}>
                  Retry cleanup
                  <ArrowRight />
                </Button>
              )}
              {state === "expired" && session?.cleanup !== "complete" && (
                <p className="helper">
                  Cleanup is pending. A new session remains blocked until
                  cleanup finishes.
                </p>
              )}
              {state === "unavailable" && (
                <Button onPress={() => void refresh()}>
                  Retry connection
                  <ArrowRight />
                </Button>
              )}
              {["ended", "expired"].includes(state) &&
                session?.cleanup === "complete" && (
                  <p className="helper">
                    Messages already submitted remain with testers and external
                    providers. A fresh session will not restore earlier links.
                  </p>
                )}
              {["ended", "expired"].includes(state) && canStart && (
                <Button onPress={() => void act("start")}>
                  Start a new test
                  <ArrowRight />
                </Button>
              )}
            </div>
          )}
        </main>
      </SidebarInset>
      <div className="prototype-toaster" ref={setToastContainer}>
        {toastContainer && <Toaster portalContainer={toastContainer} />}
      </div>
      <Dialog
        isOpen={confirmEnd !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmEnd(null);
        }}
        className="end-dialog"
      >
        <DialogTitle>End this test?</DialogTitle>
        <DialogDescription>
          <p>
            All scenario links become invalid immediately. Pending sends stop.
            Cleanup waits for provider calls already in progress.
          </p>
          <p>
            Submitted messages cannot be recalled. Temporary scenarios and
            delivery outcomes will be removed.
          </p>
        </DialogDescription>
        <DialogFooter>
          <Button variant="outline" onPress={() => setConfirmEnd(null)}>
            Keep test active
          </Button>
          <Button
            variant="destructive"
            onPress={() => {
              const owner = confirmEnd;
              setConfirmEnd(null);
              if (owner) void act("end", owner);
            }}
          >
            End Test
          </Button>
        </DialogFooter>
      </Dialog>
    </SidebarProvider>
  );
}
