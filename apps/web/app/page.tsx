async function getHealth() {
  try {
    const base = process.env.VERCEL_URL
      ? `https://${process.env.VERCEL_URL}`
      : "http://127.0.0.1:3000";
    const res = await fetch(`${base}/api/health`, { cache: "no-store" });
    return (await res.json()) as { status: string; db: string; detail?: string };
  } catch {
    return { status: "unreachable", db: "unreachable" };
  }
}

export default async function Home() {
  const health = await getHealth();
  const ok = health.status === "ok" && health.db === "connected";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-zinc-50 font-sans dark:bg-black">
      <main className="flex w-full max-w-xl flex-col gap-6 px-8">
        <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">
          RiskPilot
        </h1>
        <div className="flex items-center gap-3 rounded-lg border border-black/10 bg-white px-4 py-3 dark:border-white/10 dark:bg-zinc-950">
          <span
            className={`h-2.5 w-2.5 rounded-full ${
              ok ? "bg-green-500" : "bg-red-500"
            }`}
          />
          <span className="font-mono text-sm text-zinc-700 dark:text-zinc-300">
            api: {health.status} &middot; db: {health.db}
          </span>
        </div>
        {health.detail && (
          <p className="font-mono text-xs text-red-600 dark:text-red-400">
            {health.detail}
          </p>
        )}
      </main>
    </div>
  );
}
