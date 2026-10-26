// App shell: sidebar on desktop (lg+), bottom navigation on mobile; theme switch and sync status.
import { Link, Outlet } from "@tanstack/react-router";
import { Activity, CalendarDays, Footprints, HeartPulse, LayoutDashboard, Moon, Settings, Sun, SunMoon, TrendingUp, type LucideIcon } from "lucide-react";

import { useApi, type Schemas } from "@/api/client";
import { cx } from "@/components/ui";
import { fmtDate } from "@/lib/format";

import { useTheme, type ThemeChoice } from "./theme";

export const NAV: { to: string; label: string; short: string; icon: LucideIcon }[] = [
  { to: "/", label: "Dashboard", short: "Prehľad", icon: LayoutDashboard },
  { to: "/aktivity", label: "Aktivity", short: "Aktivity", icon: Footprints },
  { to: "/fitness", label: "Fitness", short: "Fitness", icon: Activity },
  { to: "/progres", label: "Progres", short: "Progres", icon: TrendingUp },
  { to: "/zdravie", label: "Zdravie", short: "Zdravie", icon: HeartPulse },
  { to: "/plan", label: "Plán", short: "Plán", icon: CalendarDays },
  { to: "/nastavenia", label: "Nastavenia", short: "Nastav.", icon: Settings },
];

const THEMES: { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: "light", label: "Svetlý", icon: Sun },
  { value: "dark", label: "Tmavý", icon: Moon },
  { value: "auto", label: "Auto", icon: SunMoon },
];

function SyncStatus() {
  const dash = useApi<Schemas["DashboardDTO"]>("/fitness/dashboard");
  const stale = dash.data?.sync_stale || dash.data?.last_sync === null;
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2 text-xs">
      <div className="label flex items-center gap-1.5">
        <span className={cx("h-1.5 w-1.5 rounded-full", stale ? "bg-bad" : "bg-good")} />
        Sync
      </div>
      <div className="mt-0.5 text-text">Posledný sync: {dash.data ? fmtDate(dash.data.last_sync) : "…"}</div>
    </div>
  );
}

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  return (
    <div role="radiogroup" aria-label="Režim" className="flex rounded-lg border border-line bg-card p-0.5 text-xs">
      {THEMES.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={theme === value}
          onClick={() => setTheme(value)}
          className={cx("flex flex-1 items-center justify-center gap-1 rounded-md px-1.5 py-1", theme === value ? "bg-card-2 text-text ring-1 ring-line-strong" : "text-muted")}
        >
          <Icon size={13} />
          {label}
        </button>
      ))}
    </div>
  );
}

export function Layout() {
  return (
    <div className="min-h-dvh lg:flex">
      <aside className="sticky top-0 hidden h-dvh w-56 shrink-0 flex-col border-r border-line bg-sidebar px-3 py-5 lg:flex">
        <div className="px-2">
          <div className="text-base font-bold">Training Analytics</div>
          <div className="label mt-0.5">Beh · Bicykel</div>
        </div>
        <nav className="mt-6 flex flex-col gap-0.5" aria-label="Hlavná navigácia">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              activeOptions={{ exact: to === "/" }}
              className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted hover:bg-card hover:text-text"
              activeProps={{ className: "!bg-accent/15 !text-accent font-semibold" }}
            >
              <Icon size={18} />
              {label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-2">
          <SyncStatus />
          <ThemeSwitch />
        </div>
      </aside>

      <main className="mx-auto w-full max-w-6xl px-4 pb-24 pt-5 sm:px-6 lg:px-8 lg:pb-10 lg:pt-7">
        <Outlet />
        <div className="mt-8 lg:hidden">
          <ThemeSwitch />
        </div>
      </main>

      <nav
        aria-label="Navigácia"
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-sidebar/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {NAV.map(({ to, short, icon: Icon }) => (
          <Link
            key={to}
            to={to}
            activeOptions={{ exact: to === "/" }}
            className="flex min-w-0 flex-1 flex-col items-center gap-0.5 py-2 text-[10px] text-muted"
            activeProps={{ className: "!text-accent font-semibold" }}
          >
            <Icon size={20} />
            <span className="truncate">{short}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
