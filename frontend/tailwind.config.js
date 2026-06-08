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
          950: '#ffffff',
          900: '#f8fafc',
          850: '#f1f5f9',
          800: '#e2e8f0',
          700: '#cbd5e1',
          600: '#94a3b8',
          500: '#64748b',
          400: '#475569',
          300: '#334155',
          200: '#1e293b',
          100: '#0f172a',
          50:  '#020617',
        },
        gold: {
          500: '#2563eb',
          400: '#3b82f6',
          300: '#60a5fa',
          200: '#93c5fd',
          100: '#dbeafe',
          50:  '#eff6ff',
        },
        slate: {
          950: '#020617',
        },
      },
      fontFamily: {
        display: ['Outfit', 'Noto Sans SC', 'system-ui', 'sans-serif'],
        body: ['Plus Jakarta Sans', 'Noto Sans SC', 'system-ui', 'sans-serif'],
      },
      animation: {
        float: 'float 10s ease-in-out infinite',
        'aura-pulse': 'auraPulse 8s ease-in-out infinite',
        twinkle: 'twinkle 5s ease-in-out infinite alternate',
        'fade-in': 'fadeIn 0.6s ease-out',
        'slide-up': 'slideUp 0.5s ease-out',
        'slide-in-left': 'slideInLeft 0.4s ease-out',
        shimmer: 'shimmer 2s linear infinite',
        'glow-pulse': 'glowPulse 3s ease-in-out infinite',
        grain: 'grain 8s steps(10) infinite',
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
