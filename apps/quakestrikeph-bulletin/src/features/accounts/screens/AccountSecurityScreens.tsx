import { Monitor } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { Dialog, DialogHeader, DialogTitle, DialogDescription } from "../../../components/ui/dialog";
import { BackButton } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type SecurityScreenFlow = Pick<AccountFlowState, "account" | "accountActions" | "title" | "openPhoneSettings">;

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
  const { account, accountActions, title } = flow;
  return <div className="account-action-content">
    <BackButton onPress={accountActions.openPhoneManagement} />
    {title("Remove your mobile number?", "SMS alerts will turn off. You can add a number again later.")}
    <dl className="account-removal-destination">
      <dt>Mobile number</dt>
      <dd>{account?.phone ?? "No mobile number added"}</dd>
    </dl>
    <p className="support" id="phone-removal-availability">Mobile number removal is not available yet.</p>
    <div className="account-action-buttons">
      <Button variant="outline" onPress={accountActions.openPhoneManagement}>Cancel</Button>
      <Button variant="destructive" isDisabled aria-describedby="phone-removal-availability">Remove number</Button>
    </div>
  </div>;
}

export function DevicesScreen({ flow }: { flow: SecurityScreenFlow }) {
  const { accountActions, title } = flow;
  return <div className="account-action-content">
    <BackButton onPress={accountActions.returnToAccount} />
    {title("Signed-in devices", "Manage access to your account.")}
    <div className="device-session">
      <Monitor aria-hidden="true" />
      <div>
        <h3>This device</h3>
        <p>You are signed in here.</p>
      </div>
      <Button variant="link" className="text-button" onPress={() => void accountActions.signOut()}>
        Sign out
      </Button>
    </div>
    <section className="other-devices" aria-labelledby="other-devices-title">
      <h3 id="other-devices-title">Other devices</h3>
      <p>Other signed-in devices cannot be displayed yet.</p>
      <Button variant="outline" isDisabled aria-describedby="devices-availability">Sign out other devices</Button>
      <p className="support" id="devices-availability">Device management is not available in this release.</p>
    </section>
  </div>;
}
