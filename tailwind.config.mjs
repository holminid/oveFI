/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,md,mdx,svelte,ts,tsx,vue}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      colors: {
        // Light-key “conservative future” palette
        brandAmber: '#E67C2E',
        brandBanana: '#F5D380',
        brandComplement: '#D1E2F4',
        brandPaper: '#F5F0E6',
        brandSage: '#BFD9C2',
        brandSplitComplement: '#DBF4D1',
        brandRed: '#D1422D',
        brandTeal: '#4D6F73',
        brandTriadic: '#D1F4E3',
        // Back-compat: existing classes use brandYellow
        brandYellow: '#E67C2E'
      }
    },
  },
  plugins: [
    require('@tailwindcss/aspect-ratio'),
    require('@tailwindcss/typography')
  ],
};
