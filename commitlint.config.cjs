module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // Allow emoji / longer subjects used in this repo (e.g. "fix: ... 💳").
    'header-max-length': [2, 'always', 120],
    'subject-case': [0],
    'body-max-line-length': [1, 'always', 200],
  },
};
