/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        display: ['Instrument Serif', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        shell: '#0b0b0d',
        background: '#111113',
        surface: '#161619',
        'surface-elevated': '#1e1e22',
        border: 'rgba(237, 237, 237, 0.08)',
        accent: '#2f81f7',
        primary: {
          50: '#eff6ff',
          500: '#2f81f7',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
      transitionTimingFunction: {
        craft: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
};
