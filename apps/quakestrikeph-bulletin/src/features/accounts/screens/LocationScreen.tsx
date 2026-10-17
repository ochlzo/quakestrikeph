import LocationPicker from "../LocationPicker";
import { useLayoutEffect } from "react";
import type { AccountFlowState } from "../useAccountFlow";

export function LocationScreen({ flow }: { flow: AccountFlowState; }) {
  const { account, locationEdit, savePreferences, removeLocation } = flow;
  useLayoutEffect(() => () => locationEdit.dispose(), [locationEdit]);
  return <LocationPicker edit={locationEdit} onUse={p => savePreferences({ ...p, nearbyOnly: true }, 0)}
    hasSavedLocation={account?.latitude != null && account?.longitude != null}
    onRemove={removeLocation} />;
}
