/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'sign': {
          50: '#fef7ee',
          100: '#fdedd6',
          200: '#fad7ac',
          300: '#f6ba78',
          400: '#f19342',
          500: '#ed751d',
          600: '#de5a13',
          700: '#b84312',
          800: '#933616',
          900: '#772f15',
          950: '#401509',
        },
        'blueprint': {
          50: '#eff8ff',
          100: '#dbeffe',
          200: '#bfe4fe',
          300: '#93d4fd',
          400: '#60bbfa',
          500: '#3b9df6',
          600: '#2580eb',
          700: '#1d68d8',
          800: '#1e54af',
          900: '#1e498a',
          950: '#172d54',
        },
      },
      fontFamily: {
        'display': ['Clash Display', 'system-ui', 'sans-serif'],
        'body': ['Satoshi', 'system-ui', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.5s ease-out',
        'slide-up': 'slideUp 0.5s ease-out',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideIn: {
          '0%': { opacity: '0', transform: 'translateX(-10px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
      },
    },
  },
  plugins: [],
}

