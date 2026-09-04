"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SCREENS = [
  { href: "/", label: "Live Decision Console" },
  { href: "/policy-lab", label: "Policy Lab" },
];

export function NavHeader({ endpoints }: { endpoints: string }) {
  const pathname = usePathname();

  return (
    <header className="flex items-center justify-between border-b border-zinc-800 px-6 py-4">
      <div className="flex items-baseline gap-4">
        <span className="text-sm font-semibold tracking-[0.2em] text-zinc-100 uppercase">
          RiskPilot
        </span>
        <nav className="flex gap-3">
          {SCREENS.map((screen) => (
            <Link
              key={screen.href}
              href={screen.href}
              className={`text-xs tracking-wide ${
                pathname === screen.href ? "text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
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
