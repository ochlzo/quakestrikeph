import { Button } from "../../../components/ui/button";
import { toast } from "../../../components/ui/toast";
import { FormField } from "../account-ui";
import { type Account } from "../api";
import type { AccountFlowState } from "../useAccountFlow";

export function AccountScreen({ flow }: { flow: AccountFlowState; }) {
  const {
    title, form, api, name,
    setAccount, setName, fieldErrors, submit,
    account, navigate, action, sensitive,
    user, dirty, clerk,
  } = flow;
  return (
    <>
      {title(
        "Account settings",
        "Manage your profile, verified destinations and sign-in settings.",
      )}
      <form
        onSubmit={form(async () => {
          const next = await api<Account>("/profile", "PUT", {
            displayName: name,
          });
          setAccount(next);
          setName(next.displayName);
          toast.add({ type: "success", title: "Profile saved." });
        })}
      >
        <FormField
          id="name"
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={100}
          required
          error={fieldErrors.displayName}
        />
        {submit("Save profile", false)}
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
              : "Continue with Google"}
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
              void clerk.signOut({ redirectUrl: "/" });
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
