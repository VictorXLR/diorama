import { describe, expect, it } from 'vitest';
import { generateContextWhiteboardElements } from '@/lib/whiteboardGenerator';
import type { ContextVisualization } from '@/types/context';

const SAMPLE_CONTEXT: ContextVisualization = {
  id: 'checkout-flow',
  title: 'Checkout flow',
  summary: 'A customer completes checkout through an API and payment provider.',
  diagramType: 'workflow',
  groups: [
    { id: 'client', title: 'Client experience', color: '#f8fafc' },
    { id: 'platform', title: 'Platform services', description: 'Backend processing' },
  ],
  nodes: [
    {
      id: 'cart',
      label: 'Shopping cart',
      subtitle: 'Client state',
      category: 'client',
      groupId: 'client',
    },
    {
      id: 'checkout-api',
      label: 'Checkout API',
      category: 'gateway',
      groupId: 'platform',
      status: 'active',
    },
    {
      id: 'payments',
      label: 'Payment provider',
      category: 'external',
      groupId: 'platform',
      tags: ['payments'],
    },
  ],
  connections: [
    {
      id: 'cart-to-api',
      fromNode: 'cart',
      toNode: 'checkout-api',
      label: 'Submit order',
    },
    {
      id: 'api-to-payments',
      fromNode: 'checkout-api',
      toNode: 'payments',
      style: 'dashed',
    },
  ],
  insights: [
    {
      title: 'Payment boundary',
      content: 'Keep payment credentials outside the application boundary.',
      kind: 'decision',
    },
  ],
  tags: ['checkout', 'payments'],
};

describe('generateContextWhiteboardElements', () => {
  it('renders a context header, groups, nodes, connections, and insights', () => {
    const elements = generateContextWhiteboardElements(SAMPLE_CONTEXT);

    expect(elements.length).toBeGreaterThan(0);
    expect(elements.some((element) => element.type === 'arrow')).toBe(true);
    expect(
      elements.some(
        (element) => element.type === 'rectangle' && element.backgroundColor === '#0f172a',
      ),
    ).toBe(true);
    expect(
      elements.some(
        (element) => element.type === 'rectangle' && element.backgroundColor === '#e0e7ff',
      ),
    ).toBe(true);
    expect(
      elements.some(
        (element) => element.type === 'rectangle' && element.backgroundColor === '#f0fdf4',
      ),
    ).toBe(true);
  });

  it('organizes nodes without groups into generated columns', () => {
    const contextWithoutGroups: ContextVisualization = {
      ...SAMPLE_CONTEXT,
      groups: [],
      nodes: SAMPLE_CONTEXT.nodes,
    };

    const elements = generateContextWhiteboardElements(contextWithoutGroups);

    expect(elements.some((element) => element.type === 'arrow')).toBe(true);
    expect(
      elements.some(
        (element) => element.type === 'rectangle' && element.backgroundColor === '#fef3c7',
      ),
    ).toBe(true);
  });
});
