import {jettwaveTealDark, jettwaveTealLight} from './src/codeThemes.js';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'METIS',
  tagline: 'Measurement and Evaluation of Trustworthy Intelligent Systems',
  url: 'https://govtech-responsibleai.github.io',
  baseUrl: '/metis/docs/',
  trailingSlash: false,
  favicon: 'img/metis-mark.png',
  headTags: [
    {
      tagName: 'meta',
      attributes: {name: 'algolia-site-verification', content: 'B326B139191D7CA5'},
    },
  ],
  onBrokenLinks: 'throw',
  markdown: {
    hooks: {onBrokenMarkdownLinks: 'throw'},
  },
  presets: [
    [
      'classic',
      {
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
        },
        blog: false,
        theme: {customCss: './src/css/custom.css'},
      },
    ],
  ],
  themeConfig: {
    colorMode: {defaultMode: 'light', respectPrefersColorScheme: false},
    prism: {
      theme: jettwaveTealLight,
      darkTheme: jettwaveTealDark,
      additionalLanguages: ['bash', 'yaml'],
    },
    navbar: {
      title: 'METIS',
      logo: {alt: 'METIS', src: 'img/metis-mark.png'},
      items: [
        {
          type: 'html',
          position: 'left',
          value: '<span class="navbar-docs-label">Documentation</span>',
        },
        {
          href: 'https://github.com/govtech-responsibleai/metis',
          label: 'GitHub',
          position: 'right',
          className: 'navbar-github',
        },
      ],
    },
  },
};

export default config;
