"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, FlaskConical, ShieldCheck } from "lucide-react";

const SCREENS = [
  { href: "/console", label: "Live Decision Console", icon: Activity },
  { href: "/policy-lab", label: "Policy Lab", icon: FlaskConical },
  { href: "/audit", label: "Audit & Monitoring", icon: ShieldCheck },
];

export function NavHeader({ endpoints }: { endpoints: string }) {
  const pathname = usePathname();

  return (
    <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
      <div className="flex items-baseline gap-4">
        <Link
          href="/"
          className="text-sm font-semibold tracking-[0.2em] text-zinc-100 uppercase hover:text-neon"
        >
          RiskPilot
        </Link>
        <nav className="flex gap-1">
          {SCREENS.map((screen) => {
            const active = pathname === screen.href;
            const Icon = screen.icon;
            return (
              <Link
                key={screen.href}
                href={screen.href}
                className={`flex items-center gap-1.5 border-b-2 px-2 py-1 text-xs tracking-wide ${
                  active
                    ? "border-neon text-neon"
                    : "border-transparent text-zinc-500 hover:border-zinc-700 hover:text-zinc-300"
                }`}
              >
                <Icon size={13} strokeWidth={2} />
                {screen.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <span className="font-mono text-[11px] text-zinc-600">{endpoints}</span>
    </header>
  );
}
