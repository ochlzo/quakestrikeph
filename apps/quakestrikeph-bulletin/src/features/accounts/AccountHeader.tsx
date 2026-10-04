import { Activity } from "lucide-react";

export default function AccountHeader({ publicLink = false }: { publicLink?: boolean }) {
  return (
    <header className="header">
      <a className="brand" href="/">
        <span className="brand-mark"><Activity /></span>
        <span>QuakeStrike PH<small>Bulletin</small></span>
      </a>
      <a className="back" href="/">
        <span>{publicLink ? "View Bulletin without an account" : "Back to Bulletin"}</span>
      </a>
    </header>
  );
}
