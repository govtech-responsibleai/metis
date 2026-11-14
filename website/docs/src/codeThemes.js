import {themes} from 'prism-react-renderer';

const recolour = (base, colours) => ({
  ...base,
  styles: base.styles.map(({types, style}) => ({
    types,
    style: {...style, color: colours[style.color] ?? style.color},
  })),
});

export const jettwaveTealLight = recolour(themes.jettwaveLight, {
  '#0c4a6e': '#0f766e',
  '#0ea5e9': '#14b8a6',
  '#0e7490': '#0d9488',
});

export const jettwaveTealDark = recolour(themes.jettwaveDark, {
  '#569CD6': '#2dd4bf',
  '#9CDCFE': '#99f6e4',
  '#0ea5e9': '#14b8a6',
  '#7dd3fc': '#5eead4',
});
