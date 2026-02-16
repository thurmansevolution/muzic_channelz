/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['DM Sans', 'system-ui', 'sans-serif'],
      },
      colors: {
        surface: {
          800: '#1a2332',
          700: '#222d3f',
          600: '#2a374c',
          500: '#354358',
        },
        accent: {
          400: '#5b8de6',
          500: '#4a7bd9',
        },
      },
    },
  },
  plugins: [],
}
