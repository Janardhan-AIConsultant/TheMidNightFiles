import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect } from "react";
import {
  Activity, BarChart3, Bot, CalendarDays, ClipboardCheck, FileText, LayoutDashboard, Menu, PenLine, Send, Settings, ShieldAlert, X,
} from "lucide-react";
import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";

export const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/calendar", label: "Content Calendar", icon: CalendarDays },
  { to: "/studio", label: "Content Studio", icon: PenLine },
  { to: "/approvals", label: "Approval Centre", icon: ClipboardCheck },
  { to: "/safety", label: "Safety Review", icon: ShieldAlert },
  { to: "/publishing", label: "Publishing Monitor", icon: Send },
  { to: "/distribution", label: "Distribution Plan", icon: FileText },
  { to: "/agents", label: "Agent Monitor", icon: Bot },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/logs", label: "Activity Logs", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppLayout() {
  const { navOpen, setNavOpen } = useUiStore();
  const { pathname } = useLocation();
  useEffect(() => setNavOpen(false), [pathname, setNavOpen]);

  return (
    <div className="min-h-screen md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-primary focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="flex items-center justify-between border-b border-border bg-card px-4 py-3 md:hidden">
        <span className="font-display text-lg">The Midnight Files</span>
        <Button variant="ghost" size="icon" aria-label={navOpen ? "Close menu" : "Open menu"} aria-expanded={navOpen} aria-controls="sidebar" onClick={() => setNavOpen(!navOpen)}>
          {navOpen ? <X aria-hidden /> : <Menu aria-hidden />}
        </Button>
      </header>
      <aside
        id="sidebar"
        className={cn(
          "w-full shrink-0 border-r border-border bg-card md:sticky md:top-0 md:block md:h-screen md:w-60 md:overflow-y-auto",
          navOpen ? "block" : "hidden",
        )}
      >
        <div className="hidden px-5 py-6 md:block">
          <p className="font-display text-xl leading-tight">The Midnight Files</p>
          <p className="mt-1 text-xs uppercase tracking-[0.2em] text-primary">Editorial Control</p>
        </div>
        <nav aria-label="Primary" className="px-2 pb-6">
          <ul className="space-y-0.5">
            {NAV.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                      isActive && "bg-muted text-foreground shadow-[inset_2px_0_0_hsl(var(--primary))]",
                    )
                  }
                >
                  <Icon aria-hidden className="h-4 w-4" />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 md:px-8">
        <Outlet />
      </main>
    </div>
  );
}
