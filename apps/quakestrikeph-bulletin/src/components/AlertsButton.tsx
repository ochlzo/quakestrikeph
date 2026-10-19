import { IdentityProvider, useIdentitySession } from "../lib/auth";
import { Siren } from "lucide-react";
import { LinkButton } from "./ui/button";

function AlertsLink({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <LinkButton
      className="alerts-button"
      href={signedIn ? "/alerts" : "/sign-in"}
      aria-label={signedIn ? "Alert settings" : "Receive alerts"}
    >
      <Siren data-icon="inline-start" aria-hidden="true" />
      <span>{signedIn ? "Alert settings" : "Receive alerts"}</span>
    </LinkButton>
  );
}

function SessionAlertsLink() {
  const { signedIn } = useIdentitySession();
  return <AlertsLink signedIn={signedIn} />;
}

export default function AlertsButton({
  withinAccount = false,
}: { withinAccount?: boolean } = {}) {
  if (withinAccount) return <SessionAlertsLink />;
  const publishableKey = import.meta.env.PUBLIC_CLERK_PUBLISHABLE_KEY;
  return publishableKey ? (
    <IdentityProvider publishableKey={publishableKey}>
      <SessionAlertsLink />
    </IdentityProvider>
  ) : (
    <AlertsLink />
  );
}
