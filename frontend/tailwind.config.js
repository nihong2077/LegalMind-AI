/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          900: '#0f172a',
          800: '#1e3a5f',
          700: '#264a73',
          600: '#2d5a8a',
          500: '#3b7dd8',
        },
        gold: {
          100: '#f0f4ff',
          200: '#e0e7ff',
          300: '#a5b4fc',
          400: '#2563eb',
          500: '#1d4ed8',
          600: '#1e40af',
        },
      },
      fontFamily: {
        inter: ['Inter', 'system-ui', 'sans-serif'],
      },
      animation: {
        float: 'float 10s ease-in-out infinite',
        'aura-pulse': 'auraPulse 8s ease-in-out infinite',
        twinkle: 'twinkle 5s ease-in-out infinite alternate',
        'fade-in': 'fadeIn 0.6s ease-out',
        'slide-up': 'slideUp 0.5s ease-out',
        'slide-in-left': 'slideInLeft 0.4s ease-out',
      },
      keyframes: {
        float: {
          '0%': { transform: 'translateY(-8px)' },
          '50%': { transform: 'translateY(8px)' },
          '100%': { transform: 'translateY(-8px)' },
        },
        auraPulse: {
          '0%': { opacity: '0.45', transform: 'scale(1)' },
          '50%': { opacity: '0.85', transform: 'scale(1.04)' },
          '100%': { opacity: '0.45', transform: 'scale(1)' },
        },
        twinkle: {
          '0%': { opacity: '0.4' },
          '50%': { opacity: '1' },
          '100%': { opacity: '0.4' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInLeft: {
          '0%': { opacity: '0', transform: 'translateX(-20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
}
