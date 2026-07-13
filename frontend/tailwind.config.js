/** @type {import('tailwindcss').Config} */
const withAlpha = (v) => `rgb(var(${v}) / <alpha-value>)`;

const scale = (name, stops) =>
  Object.fromEntries(stops.map((s) => [s, withAlpha(`--${name}-${s}`)]));

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        /* ── Semantic surface / text tokens ──────────────────────────── */
        app: withAlpha("--app"),
        surface: {
          DEFAULT: withAlpha("--surface"),
          raised: withAlpha("--surface"),
          sunk: withAlpha("--surface-sunk"),
        },
        border: {
          DEFAULT: withAlpha("--border"),
          strong: withAlpha("--border-strong"),
        },
        hover: withAlpha("--hover"),
        selected: withAlpha("--selected"),
        ring: withAlpha("--ring"),
        content: {
          DEFAULT: withAlpha("--text-primary"),
          secondary: withAlpha("--text-secondary"),
          muted: withAlpha("--text-muted"),
          invert: withAlpha("--text-invert"),
        },
        sidebar: {
          DEFAULT: withAlpha("--sidebar-bg"),
          text: withAlpha("--sidebar-text"),
          icon: withAlpha("--sidebar-icon"),
          muted: withAlpha("--sidebar-muted"),
          active: withAlpha("--sidebar-active-bg"),
          "active-text": withAlpha("--sidebar-active-text"),
        },

        /* ── Primitive brand scales ──────────────────────────────────── */
        navy: scale("navy", [900, 800, 700, 600, 500]),
        teal: scale("teal", [900, 800, 700, 600, 500]),
        orange: scale("orange", [900, 800, 700, 600, 500]),
        neutral: scale("neutral", [950, 900, 800, 700, 600, 500, 400, 300, 200, 100, 50]),

        /* ── Semantic status ─────────────────────────────────────────── */
        success: { DEFAULT: withAlpha("--success"), soft: withAlpha("--success-soft") },
        warning: { DEFAULT: withAlpha("--warning"), soft: withAlpha("--warning-soft") },
        danger: { DEFAULT: withAlpha("--danger"), soft: withAlpha("--danger-soft") },
        info: { DEFAULT: withAlpha("--info"), soft: withAlpha("--info-soft") },

        /* ── Legacy aliases (bridge — resolve to new palette via CSS vars) */
        canvas: { DEFAULT: withAlpha("--bg-canvas"), alt: withAlpha("--bg-canvas-alt") },
        ink: scale("ink", [900, 700, 500, 400, 300, 200, 100]),
        sage: scale("sage", [50, 100, 400, 500, 600, 700]),
        coral: scale("coral", [50, 400, 500, 600]),
        ochre: scale("ochre", [50, 400, 500, 600]),
        peri: scale("peri", [50, 400, 500, 600]),
        status: {
          paid: withAlpha("--status-paid"),
          partial: withAlpha("--status-partial"),
          unpaid: withAlpha("--status-unpaid"),
          vacant: withAlpha("--status-vacant"),
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "sans-serif",
        ],
        display: [
          "Inter",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          "sans-serif",
        ],
      },
      fontSize: {
        xs: ["12px", { lineHeight: "1.5" }],
        sm: ["13px", { lineHeight: "1.5" }],
        base: ["14px", { lineHeight: "1.6" }],
        md: ["15px", { lineHeight: "1.6" }],
        lg: ["16px", { lineHeight: "1.5" }],
        xl: ["18px", { lineHeight: "1.4" }],
        "2xl": ["20px", { lineHeight: "1.3", letterSpacing: "-0.01em" }],
        "3xl": ["24px", { lineHeight: "1.25", letterSpacing: "-0.02em" }],
        "4xl": ["30px", { lineHeight: "1.2", letterSpacing: "-0.02em" }],
        "5xl": ["36px", { lineHeight: "1.1", letterSpacing: "-0.02em" }],
      },
      borderRadius: {
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
        "2xl": "var(--r-2xl)",
        "3xl": "var(--r-3xl)",
      },
      boxShadow: {
        xs: "var(--shadow-xs)",
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        card: "var(--shadow-sm)",
        inset: "var(--shadow-inset)",
        /* Legacy aliases */
        neu: "var(--shadow-neu)",
        "neu-sm": "var(--shadow-neu-sm)",
        "neu-inset": "var(--shadow-neu-inset)",
        glass: "var(--shadow-glass)",
        float: "var(--shadow-float)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.6" },
        },
      },
      animation: {
        "fade-up": "fade-up 360ms cubic-bezier(0.22, 1, 0.36, 1) both",
        shimmer: "shimmer 1.8s linear infinite",
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
