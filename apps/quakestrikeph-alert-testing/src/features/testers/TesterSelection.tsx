import { useEffect, useState } from "react";
import { CheckboxContext } from "react-aria-components";
import { ArrowRight, Check, ChevronLeft, CircleX, Search } from "lucide-react";
import { Button } from "@quakestrikeph/ui/button";
import { Checkbox } from "@quakestrikeph/ui/checkbox";
import { Pagination, PaginationContent, PaginationItem, PaginationLink, PaginationPrevious, PaginationNext } from "@quakestrikeph/ui/pagination";
import { Field as SharedField, FieldLabel } from "@quakestrikeph/ui/field";
import { InputGroup, InputGroupInput, InputGroupAddon } from "@quakestrikeph/ui/input-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@quakestrikeph/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@quakestrikeph/ui/table";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent } from "@quakestrikeph/ui/empty";
import { Toaster, createToastManager } from "@quakestrikeph/ui/toast";
import { useWorkspace } from "../workspace/use-workspace";
import { testerRequest } from "../../lib/api";
import type { Tester, TesterResponse } from "../../../../../packages/contracts/alert-testing/testers-v1";

function ChannelEligibility({ item, channel }: { item: Tester; channel: "email" | "sms" }) {
  const value = item.channels[channel];
  return <div className="channel-eligibility">
    <span className={`status ${value.eligible ? "teal" : "neutral"}`}>{value.eligible ? <><Check size={12} />Provisionally eligible</> : "Will skip"}</span>
    <small>{value.destination}</small>
    <small>{value.enabled ? "Enabled" : "Disabled"} · {value.verified ? "Verified" : "Unverified"}</small>
    <small>{value.reason}</small>
  </div>;
}

export default function TesterSelection() {
  const workspace = useWorkspace();
  const { inputs, selected } = workspace.draft;
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [testerPageSize, setTesterPageSize] = useState(5);
  const [testerPage, setTesterPage] = useState(1);
  const [result, setResult] = useState<TesterResponse>({ accounts: [], total: 0, page: 1, pages: 1 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [toastManager] = useState(createToastManager);
  const [toastContainer, setToastContainer] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    let cancelled = false;
    if (!workspace.ready) { setLoading(true); return; }
    setLoading(true);
    const timer = setTimeout(() => {
      void testerRequest({
        session_id: workspace.owner,
        query, selected: filter === "selected" ? selected : null,
        page: testerPage, size: testerPageSize,
        event: { magnitude: inputs.magnitude, latitude: inputs.latitude, longitude: inputs.longitude },
      }).then(response => { if (!cancelled) { setResult(response); setError(null); } })
        .catch(() => { if (!cancelled) setError("Your selected testers remain intact. Retry to load the accounts."); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [workspace.ready, workspace.owner, query, filter, testerPage, testerPageSize, inputs.magnitude, inputs.latitude, inputs.longitude, filter === "selected" ? selected.join(",") : "", reload]);
  const navigate = () => void workspace.navigate("/");
  const visible = result.accounts;
  const page = result.page;
  const pageCount = result.pages;
  const total = result.total;
  const visibleIds = visible.map(item => item.id);
  const selectedVisible = visibleIds.filter(id => selected.includes(id)).length;
  function setSelected(value: string[]) {
    if (value.length > 500) {
      toastManager.add({
        id: "tester-selection-limit", type: "error",
        title: "Select at most 500 testers in one workspace.", timeout: 8000, priority: "high",
      });
      return;
    }
    workspace.edit({ inputs, selected: value });
  }
  const toggle = (id: string) => setSelected(selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id]);
  const selectVisible = (checked: boolean) => setSelected(checked ? [...new Set([...selected, ...visibleIds])] : selected.filter(id => !visibleIds.includes(id)));
    const pageCheckbox = (id: string) => (
      <CheckboxContext.Provider value={null}>
        <Checkbox
          id={id}
          aria-label="Select visible testers"
          isSelected={visible.length > 0 && selectedVisible === visible.length}
          isIndeterminate={
            selectedVisible > 0 && selectedVisible < visible.length
          }
          isDisabled={loading || !!error || !workspace.ready || !visible.length}
          onChange={selectVisible}
        />
      </CheckboxContext.Provider>
    );
    return (
      <>
        <Button
          className="back-link"
          variant="link"
          onPress={() => navigate()}
        >
          <ChevronLeft />
          Back to scenario
        </Button>
        <div className="page-heading testers-heading">
          <div>
            <h1>Select testers</h1>
            <p>Choose the Bulletin accounts that can receive this scenario.</p>
          </div>
        </div>
        <div className="table-toolbar">
          <SharedField className="tester-search">
            <FieldLabel htmlFor="tester-search" className="sr-only">
              Search testers
            </FieldLabel>
            <InputGroup>
              <InputGroupAddon>
                <Search />
              </InputGroupAddon>
              <InputGroupInput
                id="tester-search"
                aria-label="Search testers"
                placeholder="Search by name or email"
                maxLength={100}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setTesterPage(1);
                }}
              />
            </InputGroup>
          </SharedField>
          <div className="filter-buttons">
            <Button
              variant={filter === "all" ? "secondary" : "ghost"}
              onPress={() => {
                setFilter("all");
                setTesterPage(1);
              }}
            >
              All accounts
            </Button>
            <Button
              variant={filter === "selected" ? "secondary" : "ghost"}
              onPress={() => {
                setFilter("selected");
                setTesterPage(1);
              }}
            >
              Selected ({selected.length})
            </Button>
          </div>
        </div>
        {error ? (
          <Empty role="alert">
            <EmptyHeader>
              <EmptyMedia><CircleX size={32} className="text-destructive" aria-hidden="true" /></EmptyMedia>
              <EmptyTitle role="heading" aria-level={2}>Accounts could not load</EmptyTitle>
              <EmptyDescription>{error}</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
              <Button isPending={loading} isDisabled={loading} onPress={() => setReload(value => value + 1)}>Retry accounts</Button>
            </EmptyContent>
          </Empty>
        ) : <>
        <div role="status" aria-live="polite"><p>{!workspace.ready ? "Checking session…" : loading ? "Loading accounts…" : `${total} accounts · ${selected.length} selected.`}</p></div>
        <div className="desktop-table testers-table" aria-busy={loading}>
          <Table
            aria-label="Tester selection"
            className="tester-selection-table"
          >
            <TableHeader>
              <TableHead
                textValue="Select visible testers"
                aria-label="Select visible testers"
              >
                {pageCheckbox("select-desktop-page")}
              </TableHead>
              <TableHead isRowHeader>Bulletin account</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>SMS</TableHead>
              <TableHead>Saved alert rules</TableHead>
            </TableHeader>
            <TableBody
              renderEmptyState={() => (
                <p className="empty-table">No accounts match your search.</p>
              )}
            >
              {visible.map((item) => (
                <TableRow key={item.id} id={item.id} textValue={item.name}>
                  <TableCell>
                    <SharedField orientation="horizontal">
                      <Checkbox
                        aria-label={`Select ${item.name}`}
                        isSelected={selected.includes(item.id)}
                        isDisabled={loading || !!error || !workspace.ready}
                        onChange={() => toggle(item.id)}
                      />
                    </SharedField>
                  </TableCell>
                  <TableCell>
                    <div className="account-cell">
                      <span className="avatar">{item.initials}</span>
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.status} · {item.onboarding_complete ? "Onboarding complete" : "Onboarding incomplete"}</small>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    <ChannelEligibility
                      item={item}
                      channel="email"
                    />
                  </TableCell>
                  <TableCell>
                    <ChannelEligibility
                      item={item}
                      channel="sms"
                    />
                  </TableCell>
                  <TableCell>
                    <strong>M{item.threshold.toFixed(1)} or higher</strong>
                    <small>
                      {item.nearby
                        ? `Nearby only · ${item.limit} km limit`
                        : "Any location"}
                    </small>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="tester-table-footer">
          <SharedField orientation="horizontal" className="rows-per-page">
            <FieldLabel htmlFor="tester-page-size">Rows per page</FieldLabel>
            <Select
              aria-label="Rows per page"
              selectedKey={String(testerPageSize)}
              onSelectionChange={(key) => {
                setTesterPageSize(Number(key));
                setTesterPage(1);
              }}
            >
              <SelectTrigger id="tester-page-size">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="magnitude-filter-popover">
                {[5, 10, 25, 50].map((size) => (
                  <SelectItem key={size} id={String(size)}>
                    {String(size)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </SharedField>
          <Pagination aria-label="Tester pagination">
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious
                  aria-label="Previous tester page"
                  isDisabled={loading || page <= 1 || !total}
                  onPress={() => setTesterPage(page - 1)}
                />
              </PaginationItem>
              {Array.from(new Set([1, page - 1, page, page + 1, pageCount])).filter(number => number >= 1 && number <= pageCount).sort((a, b) => a - b).map(
                (number) => (
                  <PaginationItem key={number}>
                    <PaginationLink
                      aria-label={`Tester page ${number}`}
                      isActive={number === page}
                      isDisabled={loading || !total}
                      onPress={() => setTesterPage(number)}
                    >
                      {number}
                    </PaginationLink>
                  </PaginationItem>
                ),
              )}
              <PaginationItem>
                <PaginationNext
                  aria-label="Next tester page"
                  isDisabled={loading || page >= pageCount || !total}
                  onPress={() => setTesterPage(page + 1)}
                />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
          <Button
            className="use-selection"
            isDisabled={!workspace.ready}
            onPress={() => navigate()}
          >
            Use selection
            <ArrowRight />
          </Button>
        </div>
        </>}
        <div className="prototype-toaster" ref={setToastContainer}>
          {toastContainer && <Toaster toastManager={toastManager} portalContainer={toastContainer} />}
        </div>
      </>
    );
}
