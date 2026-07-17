/** Reusable Tailwind class recipes — change here to restyle the app. */

export const cx = (...parts) => parts.filter(Boolean).join(" ");

export const btn = {
  base: "inline-flex items-center justify-center gap-2 rounded-pill px-4 py-2 text-[13px] font-mono uppercase tracking-[0.08em] transition disabled:cursor-not-allowed disabled:opacity-40",
  primary: "bg-primary text-primary-fg hover:opacity-90",
  ghost: "border border-line bg-surface text-ink hover:border-line-strong",
  danger: "bg-danger text-white hover:opacity-90",
  sm: "px-3 py-1.5 text-[11px]",
  block: "w-full",
};

export function button(variant = "primary", size = "") {
  return cx(btn.base, btn[variant] || btn.primary, size === "sm" ? btn.sm : "", size === "block" ? btn.block : "");
}

export const field =
  "w-full rounded-input border border-line bg-surface px-3 py-2.5 text-[14px] text-ink outline-none focus:border-focus focus:ring-2 focus:ring-focus/20";

export const label = "mb-1.5 block text-[12px] font-mono uppercase tracking-[0.08em] text-muted";

export const panel = "rounded-card border border-line bg-surface";

export const table = {
  wrap: "w-full border-collapse text-[13px]",
  th: "border-b border-line bg-soft px-2 py-2 text-left font-mono text-[11px] uppercase tracking-[0.08em] text-muted",
  td: "border-b border-line px-2 py-2.5 align-top text-ink",
};

export function pill(status) {
  const s = String(status || "").toLowerCase();
  let tone = "border-line bg-soft text-muted";
  if (["blocking", "not_ready", "failed", "open"].includes(s) && s !== "open") {
    tone = "border-danger/30 bg-danger-soft text-danger";
  }
  if (s === "open") tone = "border-line bg-soft text-muted";
  if (["warning", "needs_review", "acknowledged", "warn"].includes(s)) {
    tone = "border-warn/30 bg-warn-soft text-warn";
  }
  if (["ready", "completed", "resolved", "dismissed", "ok"].includes(s)) {
    tone = "border-ok/30 bg-ok-soft text-ok";
  }
  if (["queued", "running"].includes(s)) {
    tone = "border-focus/30 bg-info-soft text-focus";
  }
  return `<span class="inline-block rounded-pill border px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.08em] ${tone}">${String(status).replaceAll("_", " ")}</span>`;
}
