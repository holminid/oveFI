// File: tailwind.config.mjs
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        brandPaper: '#f4e3d1',        // Albescent White
        brandTriadic: '#d1f4e3',
        brandComplement: '#d1e2f4',
        brandSplitComplement: '#dbf4d1',
      },
    },
  },
  plugins: [],
};
