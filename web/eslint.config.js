import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tseslint from 'typescript-eslint';
import sonarjs from 'eslint-plugin-sonarjs';
import reactEffects from 'eslint-plugin-react-you-might-not-need-an-effect';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import vitest from '@vitest/eslint-plugin';
import boundaries from 'eslint-plugin-boundaries';
import { localRulesPlugin } from './tools/eslint-rules/index.js';

export default [
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', '.stryker-tmp/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  sonarjs.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      'react-you-might-not-need-an-effect': reactEffects,
      'jsx-a11y': jsxA11y,
      boundaries,
      'local-rules': localRulesPlugin,
    },
    languageOptions: {
      globals: globals.browser,
      parser: tseslint.parser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    settings: {
      'import/resolver': {
        typescript: {
          alwaysTryTypes: true,
          project: ['./tsconfig.app.json'],
        },
        node: true,
      },
      'boundaries/elements': [
        {
          type: 'components',
          pattern: ['src/components/**/*', 'components/**/*'],
          partialMatch: false,
        },
        {
          type: 'lib',
          pattern: ['src/lib/**/*', 'lib/**/*'],
          partialMatch: false,
        },
        {
          type: 'types',
          pattern: ['src/types/**/*', 'types/**/*'],
          partialMatch: false,
        },
        {
          type: 'contracts',
          pattern: ['src/contracts/**/*', 'contracts/**/*'],
          partialMatch: false,
        },
        {
          type: 'app',
          pattern: ['src/**/*', '*'],
          partialMatch: false,
        },
      ],
      'boundaries/ignore': ['**/*.test.*', 'src/test/**', 'tools/**'],
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      ...reactEffects.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,

      // Anti-AI slop TypeScript rules
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-non-null-assertion': 'error',
      '@typescript-eslint/explicit-module-boundary-types': 'error',
      '@typescript-eslint/consistent-type-definitions': ['error', 'interface'],

      // Enforce aliases over relative parent paths
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['../*'],
              message: 'Imports must use the "@/" alias instead of relative parent paths ("../").',
            },
          ],
        },
      ],

      // Layer boundaries: business layers stay UI-free
      'boundaries/dependencies': [
        'error',
        {
          default: 'disallow',
          message: '{{file.type}} is not allowed to import {{dependency.type}}',
          policies: [
            {
              from: { element: { type: 'app' } },
              allow: [
                { to: { element: { type: 'app' } } },
                { to: { element: { type: 'components' } } },
                { to: { element: { type: 'lib' } } },
                { to: { element: { type: 'types' } } },
                { to: { element: { type: 'contracts' } } },
              ],
            },
            {
              from: { element: { type: 'components' } },
              allow: [
                { to: { element: { type: 'components' } } },
                { to: { element: { type: 'lib' } } },
                { to: { element: { type: 'types' } } },
                { to: { element: { type: 'contracts' } } },
              ],
            },
            {
              from: { element: { type: 'lib' } },
              allow: [
                { to: { element: { type: 'lib' } } },
                { to: { element: { type: 'types' } } },
                { to: { element: { type: 'contracts' } } },
              ],
              disallow: [
                {
                  to: { element: { type: 'components' } },
                  message:
                    'Business layers stay UI-free: a service, store, lib or type file must not import components, pages or hooks. A type shared with a form belongs in src/types or next to the service.',
                },
                {
                  to: { element: { type: 'app' } },
                  message:
                    'Business layers stay UI-free: a service, store, lib or type file must not import components, pages or hooks. A type shared with a form belongs in src/types or next to the service.',
                },
              ],
            },
            {
              from: { element: { type: 'types' } },
              allow: [
                { to: { element: { type: 'types' } } },
                { to: { element: { type: 'contracts' } } },
              ],
              disallow: [
                {
                  to: { element: { type: 'components' } },
                  message: 'Types must stay free of UI components and implementation code.',
                },
                {
                  to: { element: { type: 'app' } },
                  message: 'Types must stay free of UI components and implementation code.',
                },
                {
                  to: { element: { type: 'lib' } },
                  message: 'Types must stay free of UI components and implementation code.',
                },
              ],
            },
            {
              from: { element: { type: 'contracts' } },
              allow: [
                { to: { element: { type: 'contracts' } } },
                { to: { element: { type: 'types' } } },
              ],
              disallow: [
                {
                  to: { element: { type: 'components' } },
                  message: 'Contracts must stay free of UI components.',
                },
                {
                  to: { element: { type: 'app' } },
                  message: 'Contracts must stay free of UI components.',
                },
                {
                  to: { element: { type: 'lib' } },
                  message: 'Contracts must stay free of implementation libraries.',
                },
              ],
            },
          ],
        },
      ],

      // Sonarjs adjustments for frontend code
      'sonarjs/no-duplicate-string': ['warn', { threshold: 4 }],
    },
  },
  // Custom scar rule applied to business/service logic
  {
    files: ['src/lib/**/*.{ts,tsx}', 'src/services/**/*.{ts,tsx}'],
    plugins: {
      'local-rules': localRulesPlugin,
    },
    rules: {
      'local-rules/no-service-rounding': 'error',
    },
  },
  // Vitest test files behavior filters
  {
    files: ['**/*.test.{ts,tsx}', '**/*.spec.{ts,tsx}'],
    plugins: {
      vitest,
    },
    rules: {
      ...vitest.configs.recommended.rules,
      'vitest/expect-expect': 'error',
      'vitest/no-focused-tests': 'error',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/explicit-module-boundary-types': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
];
