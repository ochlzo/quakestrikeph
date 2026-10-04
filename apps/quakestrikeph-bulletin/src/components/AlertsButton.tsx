import { ClerkProvider, useAuth } from "@clerk/react";
import { Bell } from "lucide-react";
import { LinkButton } from "./ui/button";

function AlertsLink({ signedIn = false }: { signedIn?: boolean }) {
  return (
    <LinkButton className="alerts-button" href="/alerts">
      <Bell data-icon="inline-start" aria-hidden="true" />
      {signedIn ? "Alert settings" : "Receive alerts"}
    </LinkButton>
  );
}

function SessionAlertsLink() {
  const { isSignedIn } = useAuth();
  return <AlertsLink signedIn={isSignedIn} />;
}

export default function AlertsButton() {
  const publishableKey = import.meta.env.PUBLIC_CLERK_PUBLISHABLE_KEY;
  return publishableKey ? (
    <ClerkProvider publishableKey={publishableKey}>
      <SessionAlertsLink />
    </ClerkProvider>
  ) : <AlertsLink />;
}
