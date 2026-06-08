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
          950: '#060d1f',
          900: '#0b1529',
          850: '#0f1d38',
          800: '#142852',
          700: '#1a3666',
          600: '#1e4480',
          500: '#2558a0',
          400: '#3b7dd8',
          300: '#6ba3f0',
          200: '#a3c9f8',
          100: '#d6e6fc',
          50:  '#eef4fe',
        },
        gold: {
          600: '#8b6914',
          500: '#b8860b',
          400: '#d4a017',
          300: '#e6be44',
          200: '#f0d578',
          100: '#f7eab0',
          50:  '#fdf6e0',
        },
        slate: {
          950: '#020617',
        },
      },
      fontFamily: {
        display: ['Playfair Display', 'Noto Serif SC', 'Georgia', 'serif'],
        body: ['DM Sans', 'Noto Sans SC', 'system-ui', 'sans-serif'],
      },
      animation: {
        float: 'float 10s ease-in-out infinite',
        'aura-pulse': 'auraPulse 8s ease-in-out infinite',
        twinkle: 'twinkle 5s ease-in-out infinite alternate',
        'fade-in': 'fadeIn 0.6s ease-out',
        'slide-up': 'slideUp 0.5s ease-out',
        'slide-in-left': 'slideInLeft 0.4s ease-out',
        'shimmer': 'shimmer 2s linear infinite',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite',
        'grain': 'grain 8s steps(10) infinite',
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
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '0.4' },
          '50%': { opacity: '0.8' },
        },
        grain: {
          '0%, 100%': { transform: 'translate(0, 0)' },
          '10%': { transform: 'translate(-5%, -10%)' },
          '20%': { transform: 'translate(-15%, 5%)' },
          '30%': { transform: 'translate(7%, -25%)' },
          '40%': { transform: 'translate(-5%, 25%)' },
          '50%': { transform: 'translate(-15%, 10%)' },
          '60%': { transform: 'translate(15%, 0%)' },
          '70%': { transform: 'translate(0%, 15%)' },
          '80%': { transform: 'translate(3%, 35%)' },
          '90%': { transform: 'translate(-10%, 10%)' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
}
