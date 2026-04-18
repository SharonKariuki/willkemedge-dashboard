/** @type {import('tailwindcss').Config} */
const withAlpha = (v) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: withAlpha("--bg-canvas"),
          alt: withAlpha("--bg-canvas-alt"),
        },
        surface: {
          raised: withAlpha("--surface-raised"),
          sunk: withAlpha("--surface-sunk"),
        },
        ink: {
          900: withAlpha("--ink-900"),
          700: withAlpha("--ink-700"),
          500: withAlpha("--ink-500"),
          400: withAlpha("--ink-400"),
          300: withAlpha("--ink-300"),
          200: withAlpha("--ink-200"),
          100: withAlpha("--ink-100"),
        },
        sage: {
          50: withAlpha("--sage-50"),
          100: withAlpha("--sage-100"),
          400: withAlpha("--sage-400"),
          500: withAlpha("--sage-500"),
          600: withAlpha("--sage-600"),
          700: withAlpha("--sage-700"),
        },
        coral: {
          50: withAlpha("--coral-50"),
          400: withAlpha("--coral-400"),
          500: withAlpha("--coral-500"),
          600: withAlpha("--coral-600"),
        },
        ochre: {
          50: withAlpha("--ochre-50"),
          400: withAlpha("--ochre-400"),
          500: withAlpha("--ochre-500"),
          600: withAlpha("--ochre-600"),
        },
        peri: {
          50: withAlpha("--peri-50"),
          400: withAlpha("--peri-400"),
          500: withAlpha("--peri-500"),
          600: withAlpha("--peri-600"),
        },
        status: {
          paid: withAlpha("--status-paid"),
          partial: withAlpha("--status-partial"),
          unpaid: withAlpha("--status-unpaid"),
          vacant: withAlpha("--status-vacant"),
        },
      },
      fontFamily: {
        sans: ['"Inter Tight"', '"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Fraunces"', '"Inter Tight"', "ui-serif", "Georgia", "serif"],
      },
      borderRadius: {
        sm: "var(--r-sm)",
        md: "var(--r-md)",
        lg: "var(--r-lg)",
        xl: "var(--r-xl)",
        "2xl": "var(--r-2xl)",
      },
      boxShadow: {
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
