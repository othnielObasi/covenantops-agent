export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#141821", slate2: "#1E2530", paper: "#F5F2EC", paper2: "#EAE5DA",
        signal: "#1F6F54", amber: "#C77D2E", oxblood: "#A23B2D", mute: "#6B7280",
      },
      fontFamily: {
        display: ["'Fraunces'", "Georgia", "serif"],
        sans: ["'Inter'", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
