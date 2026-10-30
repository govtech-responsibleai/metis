import graderData from './src/data/graders.json';

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  tutorial: [
    {type: 'doc', id: 'start', label: 'Intro'},
    {type: 'doc', id: 'install', label: 'Installation'},
    {type: 'doc', id: 'prerequisites', label: 'Pre-requisites'},
    {type: 'html', value: '<hr class="sidebar-divider" aria-hidden="true" />'},
    {
      type: 'category',
      label: 'Build your specification',
      collapsed: false,
      items: [
        {type: 'doc', id: 'wizard', label: 'Specification wizard'},
        {
          type: 'category',
          label: 'Guided interview',
          collapsed: false,
          items: [
            {type: 'doc', id: 'wizard-interview', label: 'Start the interview'},
            'product-requirements',
            'test-scenarios',
          ],
        },
        {type: 'doc', id: 'specification-file', label: 'Write your own specification'},
        {type: 'doc', id: 'target-connection', label: 'Target connection'},
      ],
    },
    {
      type: 'category',
      label: 'Run your evaluations',
      link: {type: 'doc', id: 'run-evaluation'},
      collapsed: false,
      items: ['run-test-suite', 'run-graders'],
    },
    {
      type: 'category',
      label: 'Analyse your results',
      collapsed: false,
      items: ['report'],
    },
    {
      type: 'category',
      label: 'Choose your graders',
      collapsed: false,
      items: [
        'library/grader-library',
        'library/how-graders-work',
        ...graderData.groups.map(({title, graders}) => ({
          type: 'category',
          label: title,
          items: graders.map(({slug}) => `library/${slug}`),
        })),
      ],
    },
    {type: 'html', value: '<hr class="sidebar-divider" aria-hidden="true" />'},
    {type: 'doc', id: 'examples', label: 'Examples'},
  ],
};

export default sidebars;
