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
    // Docusaurus sets og:title, og:description and og:url for each page. The landing page
    // publishes this image at the site root.
    image: 'https://govtech-responsibleai.github.io/metis/og-image.png',
    metadata: [
      {name: 'twitter:card', content: 'summary_large_image'},
      {property: 'og:image:width', content: '1200'},
      {property: 'og:image:height', content: '630'},
    ],
    algolia: {
      appId: 'G7MDKDSIX0',
      // Public search-only key, so it is safe to commit.
      apiKey: '603cd515734c8d2325db9d0f0f10c9b5',
      indexName: 'metis_docs',
      contextualSearch: false,
    },
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
