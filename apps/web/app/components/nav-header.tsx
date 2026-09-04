"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SCREENS = [
  { href: "/console", label: "Live Decision Console" },
  { href: "/policy-lab", label: "Policy Lab" },
  { href: "/audit", label: "Audit & Monitoring" },
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
        <nav className="flex gap-3">
          {SCREENS.map((screen) => (
            <Link
              key={screen.href}
              href={screen.href}
              className={`text-xs tracking-wide ${
                pathname === screen.href ? "text-neon" : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {screen.label}
            </Link>
          ))}
        </nav>
      </div>
      <span className="font-mono text-[11px] text-zinc-600">{endpoints}</span>
    </header>
  );
}
