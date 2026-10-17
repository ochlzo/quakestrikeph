import { Logo } from "@quakestrikeph/ui/logo";

export default function AccountHeader({ publicLink = false }: { publicLink?: boolean }) {
  return (
    <header className="header">
      <Logo />
      <a className="back" href="/">
        <span>{publicLink ? "View Bulletin without an account" : "Back to Bulletin"}</span>
      </a>
    </header>
  );
}
