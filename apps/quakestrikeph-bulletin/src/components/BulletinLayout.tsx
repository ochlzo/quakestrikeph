import type { CSSProperties, ReactNode } from "react";
import { Activity, ChevronLeft, Earth, TextAlignStart, X } from "lucide-react";
import AlertsButton from "./AlertsButton";
import { Button } from "./ui/button";
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarHeader, SidebarProvider, SidebarTrigger, useSidebar,
} from "./ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "./ui/tabs";

function BulletinSidebar({ filters, results, settings = false, footer }: { filters: ReactNode; results: ReactNode; settings?: boolean; footer?: ReactNode }) {
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <Sidebar variant={settings ? "sidebar" : "floating"} collapsible="offcanvas" className="bulletin-sidebar">
      <SidebarHeader className="bulletin-sidebar-head">
        <div className="bulletin-sidebar-brand">
          <a className="brand" href="/" aria-label="QuakeStrike PH Bulletin home">
            <span className="brand-mark"><Activity aria-hidden="true" /></span>
            <span><strong>QuakeStrike PH</strong><small>Bulletin</small></span>
          </a>
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
            <a href="/" aria-current={settings ? undefined : "page"} onClick={() => setOpenMobile(false)}><Earth aria-hidden="true" />Earthquakes</a>
            <AlertsButton withinAccount={settings} />
            <a href="/about"><TextAlignStart aria-hidden="true" />About</a>
          </nav>
        ) : results}
      </SidebarContent>
      {footer && <SidebarFooter>{footer}</SidebarFooter>}
    </Sidebar>
  );
}

function BulletinHeader({ settings = false }: { settings?: boolean }) {
  const { isMobile, open, openMobile } = useSidebar();
  return (
    <header className="site-header bulletin-header">
      <SidebarTrigger className="aria-expanded:bg-transparent hover:aria-expanded:bg-muted" aria-label="Toggle sidebar" aria-expanded={isMobile ? openMobile : open} />
      <a className="bulletin-mobile-title" href="/" aria-label="QuakeStrike PH Bulletin home">QuakeStrike PH</a>
      {!isMobile && !settings && (
        <nav className="site-nav" aria-label="Main navigation">
          <Tabs selectedKey="/" keyboardActivation="manual">
            <TabsList aria-label="Main navigation">
              <TabsTrigger id="/" href="/">Earthquakes</TabsTrigger>
              <TabsTrigger id="/about" href="/about">About</TabsTrigger>
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

export default function BulletinLayout({ filters, results, children, settings = false, sidebarFooter }: {
  filters: ReactNode; results: ReactNode; children: ReactNode; settings?: boolean; sidebarFooter?: ReactNode;
}) {
  return (
    <SidebarProvider defaultOpen={!settings} className={`bulletin-app bulletin-shell${settings ? " bulletin-settings-shell" : ""}`} style={{ "--sidebar-width": "var(--bulletin-sidebar-width, 16rem)" } as CSSProperties}>
      <BulletinSidebar filters={filters} results={results} settings={settings} footer={sidebarFooter} />
      <div className="bulletin-main">
        <BulletinHeader settings={settings} />
        <main className="dashboard">{children}</main>
      </div>
    </SidebarProvider>
  );
}
