import { noServiceRoundingRule } from './no-service-rounding.js';

export const localRulesPlugin = {
  meta: {
    name: 'local-rules',
    version: '1.0.0',
  },
  rules: {
    'no-service-rounding': noServiceRoundingRule,
  },
};
