/**
 * Tailwind theme bridge for GridPilot.
 * Colors map to CSS variables in /assets/css/theme.css — edit tokens there to restyle everything.
 */
tailwind.config = {
  theme: {
    extend: {
      colors: {
        canvas: "var(--gp-canvas)",
        soft: "var(--gp-canvas-soft)",
        ink: "var(--gp-ink)",
        muted: "var(--gp-ink-muted)",
        faint: "var(--gp-ink-faint)",
        line: "var(--gp-border)",
        "line-strong": "var(--gp-border-strong)",
        surface: "var(--gp-surface)",
        surface2: "var(--gp-surface-2)",
        primary: "var(--gp-primary)",
        "primary-fg": "var(--gp-primary-fg)",
        focus: "var(--gp-focus)",
        danger: "var(--gp-danger)",
        "danger-soft": "var(--gp-danger-soft)",
        warn: "var(--gp-warn)",
        "warn-soft": "var(--gp-warn-soft)",
        ok: "var(--gp-ok)",
        "ok-soft": "var(--gp-ok-soft)",
        "info-soft": "var(--gp-info-soft)",
      },
      fontFamily: {
        sans: ["var(--gp-font-sans)"],
        mono: ["var(--gp-font-mono)"],
      },
      borderRadius: {
        pill: "var(--gp-radius-pill)",
        card: "var(--gp-radius-card)",
        input: "var(--gp-radius-input)",
      },
      maxWidth: {
        gp: "var(--gp-max)",
      },
      letterSpacing: {
        tightish: "-0.025em",
      },
    },
  },
};
