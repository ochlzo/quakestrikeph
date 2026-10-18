import { useEffect, useRef, useState } from "react";
import { Check, Loader, Pencil, X } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { FormField } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type AccountScreenFlow = Pick<AccountFlowState,
  "title" | "profile" | "account" | "accountActions" | "identityView" | "openPasswordSettings" | "openPhoneSettings">;

export function AccountScreen({ flow }: { flow: AccountScreenFlow; }) {
  const {
    title, profile,
    account, accountActions, identityView, openPasswordSettings, openPhoneSettings,
  } = flow;
  const { name, savedName, setName, fieldError, clearErrors, busy, saveName } = profile;
  const [editing, setEditing] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) nameInput.current?.focus(); }, [editing]);
  function discardName() {
    setName(savedName);
    clearErrors();
    setEditing(false);
  }
  return (
    <>
      {title(
        "Account settings",
        "Manage your profile, verified destinations and sign-in settings.",
      )}
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (editing && (await saveName()) === "saved") setEditing(false);
        }}
      >
        <FormField
          key={editing ? "editing" : "saved"}
          ref={nameInput}
          id="name"
          label="Name"
          labelAction={
            <div className="profile-name-actions">
              {editing ? <>
                <Button type="submit" variant="link" size="icon" className="profile-name-save"
                  aria-label="Save name" aria-busy={busy} isDisabled={busy}>
                  {busy ? <Loader className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Check aria-hidden="true" />}
                </Button>
                <Button type="button" variant="link" size="icon" className="profile-name-discard"
                  aria-label="Discard name changes" isDisabled={busy} onPress={discardName}>
                  <X aria-hidden="true" />
                </Button>
              </> : <Button type="button" variant="link" size="icon" aria-label="Edit name"
                isDisabled={busy} onPress={() => setEditing(true)}>
                <Pencil aria-hidden="true" />
              </Button>}
            </div>
          }
          value={name}
          readOnly={!editing}
          disabled={busy && editing}
          onChange={(e) => { setName(e.target.value); clearErrors(); }}
          onKeyDown={(event) => {
            if (editing && !busy && event.key === "Escape") {
              event.preventDefault();
              event.stopPropagation();
              discardName();
            }
          }}
          maxLength={100}
          required
          error={fieldError}
        />
      </form>
      <div className="account-row">
        <span>
          <strong>Email address</strong>
          <small>{account?.email} · Verified</small>
        </span>
        <Button
          variant="link"
          className="text-button"
          onPress={accountActions.openEmailChange}
        >
          Change
        </Button>
      </div>
      <div className="account-row">
        <span>
          <strong>Mobile number</strong>
          <small>{account?.phone ?? "No mobile number added"}</small>
        </span>
        <Button
          variant="link"
          className="text-button"
          onPress={() => account?.phone ? accountActions.openPhoneManagement() : void openPhoneSettings()}
        >
          {account?.phone ? "Manage" : "Add"}
        </Button>
      </div>
      <div className="account-row">
        <span>
          <strong>Password</strong>
          <small>
            {identityView.hasPassword
              ? "Password sign-in enabled"
              : "You signed in with Google. Add a password to also sign in with email"}
          </small>
        </span>
        <Button
          variant="link"
          className="text-button"
          onPress={() => void openPasswordSettings()}
        >
          {identityView.hasPassword ? "Change password" : "Add password"}
        </Button>
      </div>
      <div className="account-row">
        <span>
          <strong>Signed-in devices</strong>
          <small>Review where you are signed in.</small>
        </span>
        <Button variant="link" className="text-button" onPress={accountActions.openDevices}>
          Manage
        </Button>
      </div>
      <div className="account-links">
        <Button
          variant="link"
          className="text-button"
          onPress={() => void accountActions.signOut()}
        >
          Sign out
        </Button>
        <Button
          variant="link"
          className="danger-link"
          onPress={accountActions.openAccountRemoval}
        >
          Remove account
        </Button>
      </div>
    </>
  );
}

export function UnavailableActionScreen({ flow }: { flow: Pick<AccountFlowState, "title" | "unavailableAction">; }) {
  const { title, unavailableAction } = flow;
  return (
    <>
      {title(
        unavailableAction.removing
          ? "Account removal is unavailable"
          : "Email change is unavailable",
        "This account action is not available in the current release.",
      )}
      <p className="support">
        {unavailableAction.removing
          ? "Your account and saved settings remain available. You can turn both alert preferences off at any time."
          : "Keep using your current verified email. Your saved preferences are unaffected."}
      </p>
      <Button className="primary" onPress={unavailableAction.returnToAccount}>
        Back to account settings
      </Button>
    </>
  );
}
