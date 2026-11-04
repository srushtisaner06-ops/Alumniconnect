// AlumniConnect palette: beige · brown · silver · dusty lavender
// The default Tailwind palettes are re-mapped so every existing class (slate-*, blue-*, indigo-*, sky-*)
// automatically picks up the new theme:
//   slate  -> warm beige / brown neutrals   (backgrounds, borders, text)
//   blue   -> chocolate brown               (primary buttons, branding)
//   indigo -> dusty lavender                (accents, links, highlights)
//   sky    -> silver                        (secondary badges / icons)
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['Fraunces', 'Georgia', 'Cambria', 'Times New Roman', 'serif'],
      },
      colors: {
        slate: {
          50: '#FBF7F1', 100: '#F4ECE0', 200: '#E7DBC8', 300: '#D5C5AE', 400: '#A8978A',
          500: '#7E6D60', 600: '#605046', 700: '#4B3D34', 800: '#392E27', 900: '#281F1A',
        },
        blue: {
          50: '#F8F1EA', 100: '#EEDFCF', 200: '#DEC4AB', 300: '#C7A387', 400: '#A98162',
          500: '#8F6749', 600: '#7C5740', 700: '#6B4A3A', 800: '#593D31', 900: '#45302A',
        },
        indigo: {
          50: '#F4F1F9', 100: '#E8E2F2', 200: '#D5CBE7', 300: '#BEB1D8', 400: '#A899C8',
          500: '#9283B6', 600: '#7C6CA2', 700: '#675889', 800: '#524670', 900: '#3E3556',
        },
        sky: {
          50: '#F5F6F8', 100: '#E9EBEE', 200: '#D4D8DD', 300: '#BCC1C8', 400: '#A2A8B1',
          500: '#8A909A', 600: '#737984', 700: '#5C626D', 800: '#464B54', 900: '#33373E',
        },
        silver: { 100: '#EEF0F2', 200: '#DDE0E4', 300: '#C4C8CE', 400: '#AAAFB7', 500: '#8E949D' },
        lavender: { 100: '#EDE8F5', 200: '#D9D0EA', 300: '#C2B6DC', 400: '#AA9CCB', 500: '#9283B6' },
        beige: { 50: '#FBF7F1', 100: '#F4ECE0', 200: '#E7DBC8', 300: '#D5C5AE' },
      },
    },
  },
  plugins: [],
}
