/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        app: 'var(--bg-app)',
        surface: {
          DEFAULT: 'var(--bg-surface)',
          hover: 'var(--bg-surface-hover)',
          alt: 'var(--bg-surface-alt)',
          elevated: 'var(--bg-elevated)',
          input: 'var(--bg-input)',
        },
        border: {
          subtle: 'var(--border-subtle)',
          DEFAULT: 'var(--border-default)',
          strong: 'var(--border-strong)',
        },
        fg: {
          DEFAULT: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
          link: 'var(--text-link)',
          'on-accent': 'var(--text-on-accent)',
          'on-danger': 'var(--text-on-danger)',
        },
        control: {
          hover: 'var(--control-hover-bg)',
          active: 'var(--control-active-bg)',
          focus: 'var(--control-focus-ring)',
        },
        accent: 'rgb(var(--accent-rgb) / <alpha-value>)',
        'accent-emphasis': 'rgb(var(--accent-emphasis-rgb) / <alpha-value>)',
        success: 'rgb(var(--success-rgb) / <alpha-value>)',
        warning: 'rgb(var(--warning-rgb) / <alpha-value>)',
        danger: 'rgb(var(--danger-rgb) / <alpha-value>)',
        info: 'rgb(var(--info-rgb) / <alpha-value>)',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Microsoft YaHei UI',
          'Microsoft YaHei',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'Cascadia Code',
          'Cascadia Mono',
          'Consolas',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'monospace',
        ],
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
