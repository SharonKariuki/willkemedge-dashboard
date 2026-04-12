/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Status colours from spec — wired up so unit cards can use them on Day 2
        status: {
          paid: "#22c55e",      // green — fully paid
          partial: "#f59e0b",   // amber — partially paid
          unpaid: "#ef4444",    // red — unpaid / arrears
          vacant: "#94a3b8",    // slate — vacant
        },
      },
    },
  },
  plugins: [],
};
