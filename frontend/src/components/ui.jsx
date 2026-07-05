import React from "react";

export const statusColor = (s) =>
  s === "breach" ? "#A23B2D" : s === "watch" || s === "drifting" ? "#C77D2E" : "#1F6F54";

export function Pill({ children, tone = "signal" }) {
  const map = {
    signal: "bg-signal/15 text-signal border-signal/30",
    amber: "bg-amber/15 text-amber border-amber/30",
    oxblood: "bg-oxblood/15 text-oxblood border-oxblood/30",
    mute: "bg-white/5 text-mute border-white/10",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-wide ${map[tone]}`}>
      {children}
    </span>
  );
}

export function Panel({ title, kicker, children, className = "" }) {
  return (
    <section className={`rounded-xl border border-white/8 bg-slate2/60 backdrop-blur ${className}`}>
      {(title || kicker) && (
        <header className="flex items-baseline justify-between border-b border-white/8 px-5 py-3">
          <h3 className="font-display text-[15px] font-semibold text-paper">{title}</h3>
          {kicker && <span className="font-mono text-[11px] uppercase tracking-widest text-mute">{kicker}</span>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

// A covenant threshold gauge: value vs limit, colored by status.
export function CovenantGauge({ label, value, limit, direction, status, unit = "" }) {
  const color = statusColor(status);
  // position of value relative to limit on a 0..2x scale centered on limit
  const ratio = direction === "min" ? limit / value : value / limit;
  const pct = Math.max(4, Math.min(100, ratio * 66));
  return (
    <div className="fade-up">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-[13px] text-paper/80">{label}</span>
        <span className="font-mono text-[13px]" style={{ color }}>
          {typeof value === "number" && value > 100000 ? value.toLocaleString() : value}
          <span className="text-mute"> / {typeof limit === "number" && limit > 100000 ? limit.toLocaleString() : limit}{unit}</span>
        </span>
      </div>
      <div className="relative h-2 overflow-hidden rounded-full bg-white/6">
        <div className="scan h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
        <div className="absolute inset-y-0" style={{ left: "66%", width: 2, background: "rgba(245,242,236,.5)" }} />
      </div>
      <div className="mt-1 flex justify-between font-mono text-[10px] uppercase tracking-wider text-mute">
        <span>{direction === "min" ? "floor" : "0"}</span>
        <span style={{ color }}>{status}</span>
        <span>limit</span>
      </div>
    </div>
  );
}

// The signature: a verification seal that animates match -> valid -> sealed.
export function VerifySeal({ state }) {
  // state: "idle" | "checking" | "valid" | "invalid"
  if (state === "idle") return null;
  const valid = state === "valid";
  const checking = state === "checking";
  return (
    <div className={`seal inline-flex items-center gap-3 rounded-lg border px-4 py-3 ${
      valid ? "border-signal/40 bg-signal/10" : checking ? "border-white/15 bg-white/5" : "border-oxblood/40 bg-oxblood/10"
    }`}>
      <div className={`grid h-9 w-9 place-items-center rounded-full ${
        valid ? "bg-signal" : checking ? "bg-white/20" : "bg-oxblood"
      }`}>
        <span className="font-mono text-lg text-ink">{valid ? "✓" : checking ? "⋯" : "✗"}</span>
      </div>
      <div>
        <div className="font-display text-[14px] font-semibold" style={{ color: valid ? "#1F6F54" : checking ? "#F5F2EC" : "#A23B2D" }}>
          {valid ? "Receipt verified" : checking ? "Verifying…" : "Verification failed"}
        </div>
        <div className="font-mono text-[11px] text-mute">
          {valid ? "hash MATCH · Ed25519 VALID" : checking ? "recomputing hash · checking signature" : "hash MISMATCH · do not trust"}
        </div>
      </div>
    </div>
  );
}

export function ScoreBar({ label, value, target }) {
  const color = value >= (target || 80) ? "#1F6F54" : value >= 60 ? "#C77D2E" : "#A23B2D";
  return (
    <div className="flex items-center gap-3">
      <span className="w-40 shrink-0 text-[12px] text-paper/75">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/6">
        <div className="scan h-full rounded-full" style={{ width: `${value}%`, background: color }} />
      </div>
      <span className="w-9 text-right font-mono text-[12px]" style={{ color }}>{value}</span>
    </div>
  );
}
