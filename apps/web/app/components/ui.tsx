/**
 * Shared visual primitives for the dashboard's data-dense fintech-console
 * look (dark, monospace numerals, thin borders, no rounded bubbly chrome) -
 * used by both the Live Decision Console and the Policy Lab so the two
 * screens read as one system, not two separately-styled demos.
 */

export function formatCurrency(value: number): string {
  return `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function Panel({
  title,
  children,
  className = "",
}: {
  title: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex flex-col gap-3 border border-zinc-800 bg-zinc-950 p-4 ${className}`}>
      <h2 className="text-[11px] font-medium tracking-[0.14em] text-zinc-500 uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="tracking-wide text-zinc-500 uppercase">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "border border-zinc-800 bg-black px-2 py-1.5 font-mono text-sm text-zinc-100 outline-none focus:border-zinc-500";

export const buttonClass =
  "border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-xs font-medium tracking-wide text-zinc-200 uppercase transition-colors hover:border-zinc-500 hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40";
