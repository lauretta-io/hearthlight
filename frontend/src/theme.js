export const THEME_OPTIONS = [
  {
    key: 'fidelity-light',
    label: 'Fidelity Light',
    description: 'Professional teal light mode with the Maple and Oak primary palette.',
    group: 'light',
    colorScheme: 'light',
    swatches: ['#557e85', '#6a7a7d', '#613e23', '#eef3f1'],
  },
  {
    key: 'fidelity-dark',
    label: 'Fidelity Dark',
    description: 'Dark professional mode tuned for long monitoring sessions.',
    group: 'dark',
    colorScheme: 'dark',
    swatches: ['#78a3aa', '#203b42', '#ba8f6e', '#101819'],
  },
  {
    key: 'accessible',
    label: 'Accessible',
    description: 'High-contrast mode with stronger borders, larger contrast, and clearer focus states.',
    group: 'accessible',
    colorScheme: 'light',
    swatches: ['#004f61', '#5c2c00', '#102326', '#ffffff'],
  },
  {
    key: 'maple-oak',
    label: 'Maple & Oak',
    description: 'Warm grounded mode using the supplied maple, oak, and slate tones.',
    group: 'core',
    colorScheme: 'light',
    swatches: ['#6c7f70', '#7b6d63', '#7a4f2f', '#f3efe7'],
  },
  {
    key: 'industrial-slate',
    label: 'Industrial Slate',
    description: 'Cool neutral operations mode with steel, graphite, and teal accents.',
    group: 'core',
    colorScheme: 'light',
    swatches: ['#4f7780', '#5f6b73', '#7a5f42', '#eef1f3'],
  },
];

export const DEFAULT_THEME = 'fidelity-light';
export const THEME_STORAGE_KEY = 'hearthlight-theme';
export const THEME_GROUP_LABELS = {
  light: 'Light Mode',
  dark: 'Dark Mode',
  accessible: 'Accessible Mode',
  core: 'Core Color Themes',
};

export const getThemeOption = (themeKey) =>
  THEME_OPTIONS.find((option) => option.key === themeKey) || THEME_OPTIONS[0];
