"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, FlaskConical, ShieldCheck } from "lucide-react";
import { JOURNEY } from "@/app/components/ui";

const ICONS = { Activity, FlaskConical, ShieldCheck } as const;
const SCREEN_ICON = ["Activity", "FlaskConical", "ShieldCheck"] as const;

export function NavHeader({ endpoints }: { endpoints: string }) {
  const pathname = usePathname();
  const currentIndex = JOURNEY.findIndex((j) => j.href === pathname);

  return (
    <header className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800 px-6 py-5">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/"
          className="text-sm font-semibold tracking-[0.2em] text-zinc-100 uppercase hover:text-neon"
        >
          RiskPilot
        </Link>
        {/* The journey rail: numbered steps + connecting arrows, so moving
            between screens reads as walking through one story rather than
            picking between 3 disconnected tools from a plain nav list. */}
        <nav className="flex items-center gap-2">
          {JOURNEY.map((screen, i) => {
            const Icon = ICONS[SCREEN_ICON[i]];
            const active = i === currentIndex;
            const past = currentIndex >= 0 && i < currentIndex;
            const stateColor = active ? "text-neon" : past ? "text-zinc-300" : "text-zinc-400";
            return (
              <div key={screen.href} className="flex items-center gap-2">
                <Link
                  href={screen.href}
                  className={`flex items-center gap-1.5 border-b-2 px-1 py-1 text-xs tracking-wide transition-colors ${
                    active ? "border-neon" : "border-transparent hover:text-zinc-200"
                  } ${stateColor}`}
                >
                  <span
                    className={`flex h-4 w-4 items-center justify-center rounded-full border text-[10px] leading-none ${
                      active ? "border-neon" : "border-zinc-600"
                    }`}
                  >
                    {screen.step}
                  </span>
                  <Icon size={13} strokeWidth={2} />
                  {screen.screen}
                </Link>
                {i < JOURNEY.length - 1 && <span className="text-zinc-600">→</span>}
              </div>
            );
          })}
        </nav>
      </div>
      <span className="font-mono text-sm text-zinc-400">{endpoints}</span>
    </header>
  );
}
