import { useEffect, useRef, useState } from "react";
import { Check, Loader, Pencil, X } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/toast";
import { FormField } from "../account-ui";
import { type Account } from "../api";
import type { AccountFlowState } from "../useAccountFlow";

export function AccountScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    title, form, api, name,
    setAccount, setName, fieldErrors, setFieldErrors, busy,
    account, navigate, action, sensitive,
    user, dirty, clerk,
  } = flow;
  const [editing, setEditing] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) nameInput.current?.focus(); }, [editing]);
  function discardName() {
    setName(account?.displayName ?? "");
    setFieldErrors({});
    setEditing(false);
  }
  return (
    <>
      {title(
        "Account settings",
        "Manage your profile, verified destinations and sign-in settings.",
      )}
      <form
        onSubmit={form(async () => {
          if (!editing) return;
          const next = await api<Account>("/profile", "PUT", {
            displayName: name,
          });
          setAccount(next);
          setName(next.displayName);
          setEditing(false);
          toast.add({ type: "success", title: "Profile saved." });
        })}
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
          onChange={(e) => { setName(e.target.value); setFieldErrors({}); }}
          onKeyDown={(event) => {
            if (editing && !busy && event.key === "Escape") { event.preventDefault(); discardName(); }
          }}
          maxLength={100}
          required
          error={fieldErrors.displayName}
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
          onPress={() => navigate("change-email")}
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
          onPress={() =>
            void action(() =>
              account?.phone
                ? sensitive("phone")
                : Promise.resolve(navigate("phone")),
            )
          }
        >
          {account?.phone ? "Change" : "Add"}
        </Button>
      </div>
      <div className="account-row">
        <span>
          <strong>Password</strong>
          <small>
            {user?.passwordEnabled
              ? "Password sign-in enabled"
              : "You signed in with Google. Add a password to also sign in with email"}
          </small>
        </span>
        <Button
          variant="link"
          className="text-button"
          onPress={() => void action(() => sensitive("password"))}
        >
          {user?.passwordEnabled ? "Change password" : "Add password"}
        </Button>
      </div>
      <div className="account-links">
        <Button
          variant="link"
          className="text-button"
          onPress={() => {
            if (!dirty || window.confirm("Discard your unsaved changes?"))
              void action(() => clerk.signOut({ redirectUrl: "/" }), "Sign-out could not be completed. Please try again.");
          }}
        >
          Sign out
        </Button>
        <Button
          variant="link"
          className="danger-link"
          onPress={() => navigate("close")}
        >
          Remove account
        </Button>
      </div>
    </>
  );
}

export function UnavailableActionScreen({ flow }: { flow: AccountFlowState; }) {
  const { title, screen, setScreen } = flow;
  return (
    <>
      {title(
        screen === "close"
          ? "Account removal is unavailable"
          : "Email change is unavailable",
        "This account action is not available in the current release.",
      )}
      <p className="support">
        {screen === "close"
          ? "Your account and saved settings remain available. You can turn both alert preferences off at any time."
          : "Keep using your current verified email. Your saved preferences are unaffected."}
      </p>
      <Button className="primary" onPress={() => setScreen("account")}>
        Back to account settings
      </Button>
    </>
  );
}
