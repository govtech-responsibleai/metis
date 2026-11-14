import {readFileSync} from 'node:fs';

import {jettwaveTealDark, jettwaveTealLight} from './docs/src/codeThemes.js';

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
  staticDirectories: ['docs/static'],
  plugins: [
    // Lets a page import a file's text with `?raw`, so that `YamlFile` can show the real
    // example files from `packages/` without a copy.
    function rawImports() {
      return {
        name: 'raw-imports',
        configureWebpack() {
          return {
            module: {rules: [{resourceQuery: /raw/, type: 'asset/source'}]},
            resolve: {alias: {'@examples': new URL('../packages/engine/examples', import.meta.url).pathname}},
          };
        },
      };
    },
    // Hands the text of `GLOSSARY.md` to the bundle as `__GLOSSARY_MARKDOWN__`. A `?raw` import
    // cannot do this, because Docusaurus compiles every `.md` file as MDX before that rule runs.
    function glossaryText({siteDir}) {
      const glossaryPath = new URL('../GLOSSARY.md', `file://${siteDir}/`);
      return {
        name: 'glossary-text',
        getPathsToWatch: () => [glossaryPath.pathname],
        configureWebpack(_config, _isServer, {currentBundler}) {
          return {
            plugins: [
              new currentBundler.instance.DefinePlugin({
                __GLOSSARY_MARKDOWN__: JSON.stringify(readFileSync(glossaryPath, 'utf8')),
              }),
            ],
          };
        },
      };
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
        theme: {customCss: './docs/src/css/custom.css'},
      },
    ],
  ],
  themeConfig: {
    // A collapse arrow at the foot of the left sidebar gives a wide page more room.
    docs: {sidebar: {hideable: true}},
    // Docusaurus sets og:title, og:description and og:url for each page. The landing page
    // publishes the logo at the site root.
    image: 'https://govtech-responsibleai.github.io/metis/metis-logo.png',
    metadata: [
      {name: 'twitter:card', content: 'summary'},
      {property: 'og:image:width', content: '1254'},
      {property: 'og:image:height', content: '1254'},
    ],
    algolia: {
      appId: 'G7MDKDSIX0',
      // Public search-only key, so it is safe to commit.
      apiKey: '603cd515734c8d2325db9d0f0f10c9b5',
      indexName: 'metis_docs',
      contextualSearch: false,
    },
    colorMode: {defaultMode: 'light', respectPrefersColorScheme: true},
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
