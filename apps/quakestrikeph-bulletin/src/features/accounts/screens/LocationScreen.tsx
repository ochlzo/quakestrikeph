import LocationPicker from "../LocationPicker";
import type { AccountFlowState } from "../useAccountFlow";

export function LocationScreen({ flow }: { flow: AccountFlowState; }) {
  const { draft, setDraft, setScreen } = flow;
  return (
    <LocationPicker
      draft={draft}
      onUse={(p) => {
        setDraft((d) => ({ ...d, ...p }));
        setScreen("preferences");
      }}
      onCancel={() => setScreen("preferences")}
    />
  );
}
