// File: tailwind.config.mjs
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        brandPaper: '#f4e3d1',
        brandYellow: '#ffd600',
      },
    },
  },
  plugins: [],
};
