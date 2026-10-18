import { Monitor } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { BackButton } from "../account-ui";
import type { IdentityDevice } from "../../../lib/auth";
import type { AccountFlowState } from "../useAccountFlow";

type SecurityScreenFlow = Pick<AccountFlowState,
  "account" | "accountActions" | "title" | "openPhoneSettings" | "busy" | "devices">;

export function PhoneManagementDialog({ flow }: { flow: Pick<AccountFlowState, "account" | "phoneManagement" | "accountActions" | "openPhoneSettings"> }) {
  const { account, phoneManagement, accountActions, openPhoneSettings } = flow;
  return <Dialog className="phone-management-dialog"
    UNSTABLE_portalContainer={document.getElementById('account-workspace') ?? undefined}
    isOpen={phoneManagement.open}
    onOpenChange={open => { if (!open) phoneManagement.close(); }}>
    <DialogHeader>
      <DialogTitle>Mobile number</DialogTitle>
      <DialogDescription>Manage the number you use for SMS alerts.</DialogDescription>
    </DialogHeader>
    <p className="phone-management-number">{account?.phone}</p>
    <div className="phone-management-actions">
      <Button variant="destructive" onPress={accountActions.openPhoneRemoval}>
        Remove number
      </Button>
      <Button onPress={() => void openPhoneSettings()}>
        Change number
      </Button>
    </div>
  </Dialog>;
}

export function RemovePhoneScreen({ flow }: { flow: SecurityScreenFlow }) {
  const { account, accountActions, title, busy } = flow;
  return <div className="account-action-content">
    <BackButton onPress={accountActions.returnToAccount} />
    {title("Remove your mobile number?", "SMS alerts will turn off. You can add a number again later.")}
    <dl className="account-removal-destination">
      <dt>Mobile number</dt>
      <dd>{account?.phone ?? "No mobile number added"}</dd>
    </dl>
    <div className="account-action-buttons">
      <Button variant="outline" onPress={accountActions.returnToAccount} isDisabled={busy}>Cancel</Button>
      <Button variant="destructive" onPress={() => void accountActions.removePhone()} isDisabled={busy}>Remove number</Button>
    </div>
  </div>;
}

// Only device type, browser and relative last activity. No city, country, IP or hardware.
function deviceDetails(device: IdentityDevice) {
  return [device.deviceType, device.browser].filter(Boolean).join(" · ");
}
function lastActiveLabel(value: string | null) {
  const at = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(at)) return "Last active time unavailable";
  const minutes = Math.max(0, Math.floor((Date.now() - at) / 60000));
  if (minutes < 1) return "Active just now";
  if (minutes < 60) return `Active ${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `Active ${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.floor(hours / 24);
  return `Active ${days} day${days === 1 ? "" : "s"} ago`;
}

function DeviceRow({ device, action, busy }: { device: IdentityDevice; action: () => void; busy: boolean }) {
  const details = deviceDetails(device);
  const active = lastActiveLabel(device.lastActiveAt);
  const heading = device.current ? "This device" : details || "Device details unavailable";
  const line = device.current ? (details ? `${details} · ${active}` : "You are signed in here.") : active;
  return <div className="device-session">
    <Monitor aria-hidden="true" />
    <div>
      <h3>{heading}</h3>
      <p>{line}</p>
    </div>
    <Button variant="link" className="text-button" onPress={action} isDisabled={busy}>Sign out</Button>
  </div>;
}

export function DevicesScreen({ flow }: { flow: SecurityScreenFlow }) {
  const { accountActions, title, busy, devices } = flow;
  const current = devices.list.filter(device => device.current);
  const others = devices.list.filter(device => !device.current);
  return <div className="account-action-content">
    <BackButton onPress={accountActions.returnToAccount} />
    {title("Signed-in devices", "Manage access to your account.")}
    {devices.loading ? (
      <p className="support" role="status">Checking your signed-in devices…</p>
    ) : devices.error ? (
      <>
        <p className="support" role="alert">{devices.error}</p>
        <Button variant="outline" onPress={() => void devices.refresh()} isDisabled={busy}>Retry</Button>
      </>
    ) : (
      <>
        {current.map(device => <DeviceRow key={device.id} device={device} busy={busy}
          action={() => void accountActions.signOut()} />)}
        <section className="other-devices" aria-labelledby="other-devices-title">
          <h3 id="other-devices-title">Other devices</h3>
          {others.length === 0 ? <p>No other signed-in devices.</p> : <>
            {others.map(device => <DeviceRow key={device.id} device={device} busy={busy}
              action={() => void devices.signOut(device.id)} />)}
            <Button variant="outline" onPress={() => void devices.signOutOthers()} isDisabled={busy}>
              Sign out other devices
            </Button>
          </>}
        </section>
      </>
    )}
  </div>;
}
