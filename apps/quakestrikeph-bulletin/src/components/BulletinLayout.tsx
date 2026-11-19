import { Logo } from "@quakestrikeph/ui/logo";
import { Fragment, useState, type CSSProperties, type ReactNode } from "react";
import { ChevronLeft, Earth, FlaskConical, TextAlignStart, X } from "lucide-react";
import AlertsButton from "./AlertsButton";
import { Button } from "./ui/button";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarProvider, SidebarTrigger, useSidebar,
} from "./ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";
import { RouterProvider } from 'react-aria-components';
import { navigate } from 'astro:transitions/client';

const bulletinPages = [
  { href: "/", label: "Earthquakes", Icon: Earth },
  { href: "/simulate-forecast", label: "Simulate Forecast", Icon: FlaskConical },
  { href: "/about", label: "About", Icon: TextAlignStart },
] as const;

type BulletinPage = (typeof bulletinPages)[number]["href"];

function BulletinSidebar({ filters, results, settings = false, page = "/", footer, onHover, onFocus }: { filters?: ReactNode; results?: ReactNode; settings?: boolean; page?: BulletinPage; footer?: ReactNode; onHover?: (active: boolean) => void; onFocus?: (active: boolean) => void }) {
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <Sidebar variant={settings ? "sidebar" : "floating"} collapsible={settings ? "icon" : "offcanvas"} className="bulletin-sidebar"
      onPointerEnter={() => { if (!isMobile) onHover?.(true); }}
      onPointerLeave={() => onHover?.(false)}
      onFocusCapture={() => { if (!isMobile) onFocus?.(true); }}
      onBlurCapture={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) onFocus?.(false); }}>
      <SidebarHeader className="bulletin-sidebar-head">
        <div className="bulletin-sidebar-brand">
          <Logo />
          {isMobile && (
            <Button variant="ghost" size="icon" aria-label="Close navigation" onPress={() => setOpenMobile(false)}>
              <X aria-hidden="true" />
            </Button>
          )}
        </div>
        {!isMobile && filters}
      </SidebarHeader>
      <SidebarContent className="bulletin-sidebar-content">
        {isMobile || settings ? (
          <nav className="bulletin-mobile-nav" aria-label="Main navigation">
            {bulletinPages.filter(({ href }) => !settings || href !== "/simulate-forecast").map(({ href, label, Icon }) => (
              <Fragment key={href}>
                {href === "/about" && <AlertsButton withinAccount={settings} />}
                <a href={href} aria-current={!settings && href === page ? "page" : undefined} onClick={() => setOpenMobile(false)}>
                  <Icon aria-hidden="true" /><span>{label}</span>
                </a>
              </Fragment>
            ))}
          </nav>
        ) : results}
      </SidebarContent>
      {footer && <SidebarFooter>{footer}</SidebarFooter>}
    </Sidebar>
  );
}

function BulletinHeader({ settings = false, page = "/" }: { settings?: boolean; page?: BulletinPage }) {
  const { isMobile, open, openMobile } = useSidebar();
  const simulation = page === "/simulate-forecast";
  return (
    <header className={`site-header bulletin-header${simulation ? " simulation-header shell" : ""}`}>
      {((!settings && !simulation) || isMobile) && <SidebarTrigger className="aria-expanded:bg-transparent hover:aria-expanded:bg-muted" aria-label="Toggle sidebar" aria-expanded={isMobile ? openMobile : open} />}
      {simulation && <Logo className="simulation-brand" />}
      <a className="bulletin-mobile-title" href="/" aria-label="QuakeStrike PH Bulletin home">QuakeStrike PH</a>
      {!isMobile && !settings && (
        <nav className="site-nav" aria-label="Main navigation">
          <Tabs selectedKey={page} keyboardActivation="manual">
            <TabsList aria-label="Main navigation">
              {bulletinPages.map(({ href, label }) => (
                <TabsTrigger key={href} id={href} href={href} aria-current={href === page ? "page" : undefined}>
                  <span className="bulletin-nav-indicator" aria-hidden="true" />
                  <span className="bulletin-nav-label">{label}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        </nav>
      )}
      {settings ? (
        <a className="settings-bulletin-back" href="/" aria-label="Back to Bulletin">
          <ChevronLeft aria-hidden="true" /><span>Back to Bulletin</span>
        </a>
      ) : <AlertsButton />}
    </header>
  );
}

function SimulationMobileSidebar() {
  const { isMobile } = useSidebar();
  return isMobile ? <BulletinSidebar page="/simulate-forecast" /> : null;
}

export function SimulationHeader() {
  return (
    <RouterProvider navigate={(href) => void navigate(href)}>
      <SidebarProvider defaultOpen={false} className="simulation-header-shell min-h-0">
        <SimulationMobileSidebar />
        <BulletinHeader page="/simulate-forecast" />
      </SidebarProvider>
    </RouterProvider>
  );
}

export default function BulletinLayout({ filters, results, children, settings = false, sidebarFooter, sidebarMenuOpen = false }: {
  filters: ReactNode; results: ReactNode; children: ReactNode; settings?: boolean; sidebarFooter?: ReactNode; sidebarMenuOpen?: boolean;
}) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <RouterProvider navigate={(href) => void navigate(href)}>
    <SidebarProvider defaultOpen={!settings} {...(settings ? { open: hovered || focused || sidebarMenuOpen, onOpenChange: () => {} } : {})} className={`bulletin-app bulletin-shell${settings ? " bulletin-settings-shell" : ""}`} style={{ "--sidebar-width": "var(--bulletin-sidebar-width, 16rem)" } as CSSProperties}>
      <BulletinSidebar filters={filters} results={results} settings={settings} footer={sidebarFooter} onHover={setHovered} onFocus={setFocused} />
      <div className="bulletin-main">
        <BulletinHeader settings={settings} />
        <main className="dashboard">{children}</main>
      </div>
    </SidebarProvider>
    </RouterProvider>
  );
}
