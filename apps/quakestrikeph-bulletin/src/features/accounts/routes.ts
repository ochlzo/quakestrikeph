export type Screen =
  | "signin"
  | "signup"
  | "verify-email"
  | "device-code"
  | "forgot"
  | "recovery-code"
  | "reset"
  | "profile"
  | "channels"
  | "phone"
  | "verify-phone"
  | "preferences"
  | "location"
  | "account"
  | "reverify"
  | "password"
  | "change-email"
  | "close";

export type AccountDestination = "preferences" | "location" | "account";

export const accountRoutes = {
  "/sign-in": "signin",
  "/sign-up": "signup",
  "/forgot-password": "forgot",
  "/onboarding": "profile",
  "/alerts": "preferences",
  "/alerts/location": "location",
  "/account": "account",
  "/account/password": "password",
  "/account/phone": "phone",
} as const satisfies Record<string, Screen>;

export function screenAtPath(pathname: string): Screen | undefined {
  return accountRoutes[pathname.replace(/\/$/, "") as keyof typeof accountRoutes];
}

export function initialScreen(initial: string): Screen {
  if (initial === "alerts") return "preferences";
  if (initial === "onboarding") return "profile";
  return (Object.values(accountRoutes) as string[]).includes(initial)
    ? initial as Screen : "signin";
}

export function pathForScreen(screen: Screen, onboarding = false): string {
  if (onboarding && ["profile", "channels", "phone", "verify-phone", "preferences", "location"].includes(screen))
    return "/onboarding";
  switch (screen) {
    case "signin": case "device-code": return "/sign-in";
    case "signup": case "verify-email": return "/sign-up";
    case "forgot": case "recovery-code": case "reset": return "/forgot-password";
    case "profile": case "channels": return "/onboarding";
    case "preferences": return "/alerts";
    case "location": return "/alerts/location";
    case "password": return "/account/password";
    case "phone": case "verify-phone": return "/account/phone";
    default: return "/account";
  }
}

export function isPublicAccountScreen(screen: Screen): boolean {
  return ["signin", "signup", "forgot", "verify-email", "device-code", "recovery-code", "reset"].includes(screen);
}

// History stores navigation position only. Credentials and drafts stay in React state.
export function writeAccountRoute(path: string, replace = false): void {
  const samePath = location.pathname === path;
  const index = typeof history.state?.accountIndex === "number" ? history.state.accountIndex : 0;
  history[replace || samePath ? "replaceState" : "pushState"](
    { ...history.state, accountIndex: index + (replace || samePath ? 0 : 1) }, "", path,
  );
}
