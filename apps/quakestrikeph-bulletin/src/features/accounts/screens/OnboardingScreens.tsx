import { ArrowRight, Mail, Phone } from "lucide-react";
import { Button } from "../../../components/ui/button";
import { FormField } from "../account-ui";
import type { AccountFlowState } from "../useAccountFlow";

type ProfileScreenFlow = Pick<AccountFlowState, "title" | "identityView" | "profile" | "submit" | "signOut">;

export function ProfileScreen({ flow }: { flow: ProfileScreenFlow; }) {
  const {
    title, identityView, profile, submit, signOut,
  } = flow;
  const { name, setName, fieldError, busy, continueProfile } = profile;
  return (
    <>
      {title(
        "Complete your profile",
        identityView.email ? (
          <>
            Choose the name for your personal settings for{" "}
            <strong className="profile-email">
              {identityView.email}
            </strong>
            .
          </>
        ) : (
          "Choose the name to use for your personal settings."
        ),
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void continueProfile();
        }}
      >
        <FormField
          id="name"
          label="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={100}
          autoComplete="name"
          required
          error={fieldError}
        />
        <div className="profile-actions">
          {submit("Continue")}
          <Button
            type="button"
            className="secondary"
            isDisabled={busy}
            onPress={() => void signOut()}
          >
            Cancel and sign out
          </Button>
        </div>
      </form>
    </>
  );
}

export function ChannelsScreen({ flow }: { flow: AccountFlowState; }) {
  const { title, channels, setChannels, action, busy, saveOnboardingChannels } = flow;
  return (
    <>
      {title(
        "How would you like to receive alerts?",
        "Choose Email, SMS, or both. Continue saves your choices. SMS is enabled after verification.",
      )}
      <fieldset className="choices">
        <legend>Receive options</legend>
        {[
          ["sms", "SMS", "Verify a supported Philippine mobile number."],
          ["email", "Email", "Use your verified account email."],
        ].map(([id, label, text]) => (
          <label className="choice" key={id}>
            <input
              type="checkbox"
              name="channel"
              value={id}
              checked={channels.includes(id)}
              onChange={(event) =>
                setChannels((selected) =>
                  event.target.checked
                    ? [...selected, id]
                    : selected.filter((channel) => channel !== id),
                )
              }
            />
            <span>
              <strong>{label}</strong>
              <small>{text}</small>
            </span>
            {id === "sms" ? <Phone /> : <Mail />}
          </label>
        ))}
        <div className="choice-alternative">
          <label className="choice">
            <input
              type="checkbox"
              name="channel"
              value="none"
              checked={channels.length === 0}
              onChange={() => setChannels([])}
            />
            <span>
              <strong>Neither for now</strong>
              <small>Save your settings with both channels off.</small>
            </span>
          </label>
        </div>
      </fieldset>
      <Button
        className="primary"
        isDisabled={busy}
        onPress={() => void action(saveOnboardingChannels)}
      >
        Continue
        <ArrowRight />
      </Button>
    </>
  );
}
