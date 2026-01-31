import { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Activity,
  LayoutDashboard,
  ListChecks,
  ShieldCheck,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

function SideLink({
  to,
  icon,
  label,
}: {
  to: string;
  icon: ReactNode;
  label: string;
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition",
          isActive
            ? "bg-slate-900 text-slate-50"
            : "text-slate-300 hover:bg-slate-900/60 hover:text-slate-50"
        )
      }
      end
    >
      <span className="h-4 w-4">{icon}</span>
      <span>{label}</span>
    </NavLink>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0B1220] text-slate-100">
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-[#0B1220]/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-slate-900">
              <Activity className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold">Robot Eval Platform</div>
              <div className="text-xs text-slate-400">
                Runs • Gates • Reports
              </div>
            </div>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl grid-cols-12 gap-4 px-4 py-6">
        <aside className="col-span-12 md:col-span-3 lg:col-span-2">
          <nav className="space-y-1 rounded-xl border border-slate-800 bg-slate-950/40 p-2">
            <SideLink
              to="/"
              icon={<LayoutDashboard className="h-4 w-4" />}
              label="Overview"
            />
            <SideLink
              to="/runs"
              icon={<ListChecks className="h-4 w-4" />}
              label="Runs"
            />
            <SideLink
              to="/gates"
              icon={<ShieldCheck className="h-4 w-4" />}
              label="Gates"
            />
            <SideLink
              to="/settings"
              icon={<Settings className="h-4 w-4" />}
              label="Settings"
            />
          </nav>
        </aside>

        <main className="col-span-12 md:col-span-9 lg:col-span-10">
          {children}
        </main>
      </div>
    </div>
  );
}
