export const noServiceRoundingRule = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Prevent rounding inside service/lib code to avoid cumulative rounding errors (the double-rounding scar).',
      category: 'Possible Errors',
      recommended: true,
    },
    messages: {
      noRounding:
        'Services compute, formatters round. Rounding twice moves the value off its true one: Math.round(h * 10) / 10 turned a 26h15m total into 26h18m. Do not use {{method}} in service/lib logic.',
    },
    schema: [],
  },
  create(context) {
    return {
      CallExpression(node) {
        const callee = node.callee;
        if (
          callee.type === 'MemberExpression' &&
          callee.object.type === 'Identifier' &&
          callee.object.name === 'Math' &&
          callee.property.type === 'Identifier' &&
          callee.property.name === 'round'
        ) {
          context.report({
            node,
            messageId: 'noRounding',
            data: { method: 'Math.round' },
          });
        }

        if (
          callee.type === 'MemberExpression' &&
          callee.property.type === 'Identifier' &&
          callee.property.name === 'toFixed'
        ) {
          context.report({
            node,
            messageId: 'noRounding',
            data: { method: '.toFixed()' },
          });
        }
      },
    };
  },
};
