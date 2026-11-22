/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Pretendard Variable", "Pretendard", "Noto Sans KR", "sans-serif"]
      },
      colors: {
        ink: "#10243E",
        navy: "#102C4C",
        cobalt: "#2563EB",
        teal: "#12A594"
      },
      boxShadow: {
        card: "0 12px 32px rgba(18, 45, 75, 0.07)"
      }
    }
  },
  plugins: []
};

