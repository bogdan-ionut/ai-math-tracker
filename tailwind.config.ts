import type { Config } from "tailwindcss";

/**
 * Colors are driven by CSS custom properties (see styles/globals.css) so the
 * whole palette swaps between light and dark in one place. Tailwind utilities
 * reference the tokens via rgb(var(--token) / <alpha>).
 */
const withOpacity = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: withOpacity("--void"),
        panel: withOpacity("--panel"),
        "panel-2": withOpacity("--panel-2"),
        ink: withOpacity("--ink"),
        "ink-2": withOpacity("--ink-2"),
        muted: withOpacity("--muted"),
        rule: withOpacity("--rule"),
        good: withOpacity("--good"),
        lab: {
          oa: withOpacity("--lab-oa"),
          dm: withOpacity("--lab-dm"),
          cg: withOpacity("--lab-cg"),
          ax: withOpacity("--lab-ax"),
          an: withOpacity("--lab-an"),
          xa: withOpacity("--lab-xa"),
          pk: withOpacity("--lab-pk"),
        },
      },
      fontFamily: {
        display: ["'Bodoni Moda'", "Didot", "Georgia", "serif"],
        sans: ["'Inter Variable'", "Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      borderColor: { DEFAULT: "rgb(var(--rule) / 1)" },
      borderRadius: { xl2: "0.875rem" },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: { "fade-up": "fade-up 0.4s ease both" },
    },
  },
  plugins: [],
} satisfies Config;
