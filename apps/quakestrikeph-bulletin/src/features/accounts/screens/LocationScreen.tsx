import LocationPicker from "../LocationPicker";
import { useEffect } from "react";
import type { AccountFlowState } from "../useAccountFlow";

export function LocationScreen({ flow }: { flow: AccountFlowState; }) {
  const { draft, setDraft, setLocationEdit } = flow;
  useEffect(() => () => setLocationEdit(null), [setLocationEdit]);
  return (
    <LocationPicker
      draft={draft}
      onEditChange={setLocationEdit}
      validationAttempt={flow.locationValidation}
      onUse={(p) => {
        setDraft((d) => ({ ...d, ...p }));
      }}
    />
  );
}
