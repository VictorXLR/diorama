import { describe, it } from 'vitest';
import { RuleTester } from 'eslint';
import { noServiceRoundingRule } from './no-service-rounding.js';

RuleTester.describe = describe;
RuleTester.it = it;

const ruleTester = new RuleTester({
  languageOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
});

ruleTester.run('no-service-rounding', noServiceRoundingRule, {
  valid: [
    { code: 'const total = hours * 60 + minutes;' },
    { code: 'const average = sum / count;' },
    { code: 'const val = Math.floor(x);' },
  ],
  invalid: [
    {
      code: 'const rounded = Math.round(h * 10) / 10;',
      errors: [
        {
          message:
            'Services compute, formatters round. Rounding twice moves the value off its true one: Math.round(h * 10) / 10 turned a 26h15m total into 26h18m. Do not use Math.round in service/lib logic.',
        },
      ],
    },
    {
      code: 'const formatted = total.toFixed(2);',
      errors: [
        {
          message:
            'Services compute, formatters round. Rounding twice moves the value off its true one: Math.round(h * 10) / 10 turned a 26h15m total into 26h18m. Do not use .toFixed() in service/lib logic.',
        },
      ],
    },
  ],
});

