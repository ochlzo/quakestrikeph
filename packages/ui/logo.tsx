import type { ComponentProps } from "react";
import { Earth } from "lucide-react";
import "./logo.css";

type LogoProps = ComponentProps<"a"> & { subtitle?: string };

export function Logo({ subtitle = "Bulletin", href = "/", className = "", ...props }: LogoProps) {
  return (
    <a className={`brand ${className}`} href={href} aria-label={`QuakeStrike PH ${subtitle} home`} {...props}>
      <span className="brand-mark"><Earth aria-hidden="true" /></span>
      <span className="bulletin-brand-label"><strong>QuakeStrike PH</strong><small>{subtitle}</small></span>
    </a>
  );
}
