import { NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

function navClass({ isActive }: { isActive: boolean }) {
  return cn(
    "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
    isActive
      ? "bg-primary text-primary-foreground"
      : "text-muted-foreground hover:text-foreground hover:bg-accent",
  );
}

export function Layout() {
  return (
    <div className="min-h-full flex flex-col">
      <header className="sticky top-0 z-20 bg-background/85 backdrop-blur border-b">
        <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center gap-6">
          <div className="font-semibold">PIN Ticket Analysis</div>
          <nav className="flex items-center gap-1">
            <NavLink to="/pins" className={navClass}>
              PIN List
            </NavLink>
            <NavLink to="/dashboard" className={navClass}>
              Dashboard
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="flex-1 max-w-[1400px] mx-auto w-full px-6 py-6">
        <Outlet />
      </main>
    </div>
  );
}
