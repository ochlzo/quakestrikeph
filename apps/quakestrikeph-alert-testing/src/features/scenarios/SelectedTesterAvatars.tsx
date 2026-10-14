import { useEffect, useState } from "react";
import { Skeleton } from "@quakestrikeph/ui/skeleton";
import { testerRequest } from "../../lib/api";
import type { Tester } from "../../../../../packages/contracts/alert-testing/testers-v1";

export function SelectedTesterAvatars({ selected, owner, ready }: {
  selected: string[];
  owner: string | null;
  ready: boolean;
}) {
  const visibleIds = selected.slice(0, 4);
  const key = JSON.stringify([owner, visibleIds]);
  const [result, setResult] = useState<{ key: string; accounts: Tester[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    if (!ready || !owner || !visibleIds.length) return;
    void testerRequest({
      session_id: owner, query: "", selected: visibleIds, page: 1, size: 5,
      // This row reads identities only, so it does not evaluate event eligibility.
      event: { magnitude: "", latitude: "", longitude: "" },
    }).then(response => {
      if (!cancelled) setResult({ key, accounts: response.accounts });
    }).catch(() => {
      if (!cancelled) setError("unavailable");
    });
    return () => { cancelled = true; };
  }, [key, ready]);

  const accounts = ready && result?.key === key ? result.accounts : null;
  const loading = !ready || (selected.length > 0 && !accounts && !error);
  return (
    <div className="avatar-list" aria-busy={loading}>
      {loading ? visibleIds.map(id => (
        <Skeleton key={id} className="size-7 rounded-full shrink-0 -mr-1" />
      )) : visibleIds.map(id => {
        const account = accounts?.find(item => item.id === id);
        return account ? <span key={id} title={account.name} aria-label={account.name}>{account.initials}</span> : null;
      })}
      {selected.length > 4 && <span>+{selected.length - 4}</span>}
      {!ready ? <Skeleton className="h-3 w-20 ml-3" /> : (
        <strong>{selected.length} {selected.length === 1 ? "account" : "accounts"}</strong>
      )}
    </div>
  );
}
