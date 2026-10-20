import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  BookOpen,
  Dumbbell,
  Flag,
  Home as HomeIcon,
  LayoutDashboard,
  LogOut,
  Link2,
  NotebookPen,
  Sparkles,
} from "lucide-react";
import { Link, useLocation } from "wouter";
import LoginPage from "@/pages/Login";

const NAV = [
  { href: "/", label: "Home", icon: HomeIcon },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/platforms", label: "Platforms & Sync", icon: Link2 },
  { href: "/coach", label: "Coach", icon: BookOpen },
  { href: "/recommendations", label: "Recommendations", icon: Sparkles },
  { href: "/reflections", label: "Reflections", icon: NotebookPen },
  { href: "/contests", label: "Contests", icon: Flag },
  { href: "/knowledge", label: "Knowledge", icon: Dumbbell },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, loading, error, logout } = useAuth();
  const [location] = useLocation();

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-background text-sm text-muted-foreground">
        Checking your session…
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-4 px-5 py-3">
          <Link href="/" className="flex items-center gap-2">
            <img
              src="/rethink-icon.png"
              alt="Re.Think"
              className="h-8 w-8 rounded-lg object-cover"
            />
            <span className="text-lg font-semibold tracking-tight">Re.Think</span>
          </Link>

          <nav className="flex flex-1 flex-wrap items-center gap-1">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = location === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-secondary text-secondary-foreground"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3">
            <div className="text-right text-xs leading-tight">
              <div className="font-medium text-foreground">{user.name || user.username}</div>
              <div className="text-muted-foreground">
                {user.username} · #{user.backendUserId}
              </div>
            </div>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              <LogOut className="mr-1 h-4 w-4" />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      {error ? (
        <div className="mx-auto max-w-6xl px-5 pt-4 text-sm text-destructive">{error}</div>
      ) : null}

      <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
    </div>
  );
}
