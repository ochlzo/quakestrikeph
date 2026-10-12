import LocationPicker from "../LocationPicker";
import { useLayoutEffect } from "react";
import type { AccountFlowState } from "../useAccountFlow";

export function LocationScreen({ flow }: { flow: AccountFlowState; }) {
  const { locationEdit, savePreferences } = flow;
  useLayoutEffect(() => () => locationEdit.dispose(), [locationEdit]);
  return <LocationPicker edit={locationEdit} onUse={p => savePreferences(p, 0)} />;
}
