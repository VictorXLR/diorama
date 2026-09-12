import { convertToExcalidrawElements } from '@excalidraw/excalidraw';
import type {
  ExcalidrawSkeletonElement,
  ContextVisualization,
  NodeCategory,
} from '@/types/context';

export type WhiteboardElements = ReturnType<typeof convertToExcalidrawElements>;

type ExcalidrawSkeleton = Parameters<typeof convertToExcalidrawElements>[0];

const NODE_COLORS: Record<NodeCategory, { bg: string; stroke: string }> = {
  client: { bg: '#e0e7ff', stroke: '#4338ca' },
  gateway: { bg: '#fef3c7', stroke: '#b45309' },
  service: { bg: '#dcfce7', stroke: '#15803d' },
  database: { bg: '#fee2e2', stroke: '#b91c1c' },
  queue: { bg: '#f3e8ff', stroke: '#7e22ce' },
  storage: { bg: '#ffedd5', stroke: '#c2410c' },
  external: { bg: '#f1f5f9', stroke: '#475569' },
  workflow_step: { bg: '#e0f2fe', stroke: '#0369a1' },
  concept: { bg: '#fdf4ff', stroke: '#a21caf' },
  custom: { bg: '#f8fafc', stroke: '#334155' },
};

export function convertServerWhiteboardElements(
  elements: ExcalidrawSkeletonElement[],
): WhiteboardElements {
  return convertToExcalidrawElements(elements as ExcalidrawSkeleton);
}

export function generateContextWhiteboardElements(
  context: ContextVisualization,
): WhiteboardElements {
  const skeletons: ExcalidrawSkeletonElement[] = [];

  const startX = 80;
  const startY = 80;
  const colWidth = 280;
  const colGap = 60;
  const nodeHeight = 110;
  const nodeGap = 35;

  const groups = [...context.groups];
  const groupedNodes: Record<string, typeof context.nodes> = {};
  const ungroupedNodes: typeof context.nodes = [];

  for (const group of groups) {
    groupedNodes[group.id] = [];
  }

  for (const node of context.nodes) {
    const targetGroup = node.groupId ? groupedNodes[node.groupId] : undefined;
    if (targetGroup) {
      targetGroup.push(node);
    } else {
      ungroupedNodes.push(node);
    }
  }

  if (ungroupedNodes.length > 0) {
    if (groups.length > 0) {
      const defaultGid = 'group-general';
      groups.push({
        id: defaultGid,
        title: 'Core Components',
        description: 'General subsystem',
      });
      groupedNodes[defaultGid] = ungroupedNodes;
    } else {
      const colsCount = Math.max(1, Math.min(3, Math.ceil(context.nodes.length / 3)));
      for (let i = 0; i < colsCount; i++) {
        const gid = `col-${i + 1}`;
        groups.push({ id: gid, title: `Tier ${i + 1}` });
        groupedNodes[gid] = [];
      }
      context.nodes.forEach((node, i) => {
        const gid = `col-${(i % colsCount) + 1}`;
        groupedNodes[gid]?.push(node);
      });
    }
  }

  const numCols = Math.max(1, groups.length);
  const totalWidth = Math.max(980, numCols * (colWidth + colGap) + 380);

  // 1. Header Banner Widget (drawn by Excalidraw)
  skeletons.push({
    type: 'rectangle',
    x: startX,
    y: startY,
    width: totalWidth,
    height: 115,
    backgroundColor: '#0f172a',
    strokeColor: '#1e293b',
    fillStyle: 'solid',
    roundness: { type: 3 },
    roughness: 0,
    label: {
      text: `[${context.diagramType.toUpperCase().replace('_', ' ')}] ${context.title.toUpperCase()}\n${context.summary}`,
      fontSize: 18,
      textAlign: 'left',
      verticalAlign: 'middle',
    },
  });

  const nodeBounds: Record<string, { x: number; y: number; w: number; h: number }> = {};

  for (const [colIdx, group] of groups.entries()) {
    const colX = startX + colIdx * (colWidth + colGap);
    const groupNodes = groupedNodes[group.id] || [];
    const colY = startY + 145;
    const innerContentHeight = Math.max(160, 50 + groupNodes.length * (nodeHeight + nodeGap));

    // Group Container Widget
    skeletons.push({
      type: 'rectangle',
      x: colX - 12,
      y: colY,
      width: colWidth + 24,
      height: innerContentHeight + 20,
      backgroundColor: group.color || '#f8fafc',
      strokeColor: '#94a3b8',
      strokeStyle: 'dashed',
      fillStyle: 'solid',
      roundness: { type: 3 },
      roughness: 0,
      strokeWidth: 1.5,
      opacity: 80,
    });

    // Group Header Label
    skeletons.push({
      type: 'text',
      x: colX,
      y: colY + 12,
      text: group.description ? `${group.title.toUpperCase()}\n${group.description}` : group.title.toUpperCase(),
      fontSize: 14,
      textAlign: 'left',
      verticalAlign: 'top',
      strokeColor: '#334155',
    });

    let currY = colY + 55;

    for (const node of groupNodes) {
      const colors = NODE_COLORS[node.category] || { bg: '#f8fafc', stroke: '#475569' };
      const headerLine = `[${node.category.toUpperCase()}] ${node.label}`;
      const details = [
        node.subtitle,
        node.description,
        node.status ? `Status: ${node.status}` : '',
        node.tags && node.tags.length > 0 ? `Tags: ${node.tags.join(', ')}` : '',
      ].filter(Boolean);

      const cardText = details.length > 0 ? `${headerLine}\n${details.join('\n')}` : headerLine;

      skeletons.push({
        type: 'rectangle',
        x: colX,
        y: currY,
        width: colWidth,
        height: nodeHeight,
        backgroundColor: colors.bg,
        strokeColor: colors.stroke,
        fillStyle: 'solid',
        roundness: { type: 3 },
        roughness: 1,
        strokeWidth: 2,
        label: {
          text: cardText,
          fontSize: 13,
          textAlign: 'left',
          verticalAlign: 'middle',
        },
      });

      nodeBounds[node.id] = { x: colX, y: currY, w: colWidth, h: nodeHeight };
      currY += nodeHeight + nodeGap;
    }
  }

  // 3. Connectors Widget
  for (const conn of context.connections) {
    const fromB = nodeBounds[conn.fromNode];
    const toB = nodeBounds[conn.toNode];
    if (!fromB || !toB) continue;

    const fromCx = fromB.x + fromB.w / 2;
    const fromCy = fromB.y + fromB.h / 2;
    const toCx = toB.x + toB.w / 2;
    const toCy = toB.y + toB.h / 2;

    let startPt: [number, number];
    let endPt: [number, number];

    if (Math.abs(toCx - fromCx) > Math.abs(toCy - fromCy)) {
      if (toCx > fromCx) {
        startPt = [fromB.x + fromB.w, fromCy];
        endPt = [toB.x, toCy];
      } else {
        startPt = [fromB.x, fromCy];
        endPt = [toB.x + toB.w, toCy];
      }
    } else {
      if (toCy > fromCy) {
        startPt = [fromCx, fromB.y + fromB.h];
        endPt = [toCx, toB.y];
      } else {
        startPt = [fromCx, fromB.y];
        endPt = [toCx, toB.y + toB.h];
      }
    }

    const dx = endPt[0] - startPt[0];
    const dy = endPt[1] - startPt[1];

    skeletons.push({
      type: 'arrow',
      x: startPt[0],
      y: startPt[1],
      points: [
        [0, 0],
        [dx, dy],
      ],
      strokeColor: '#6366f1',
      strokeWidth: 2,
      strokeStyle: conn.style || 'solid',
      roundness: { type: 2 },
      ...(conn.label ? {
        label: {
          text: conn.label,
          fontSize: 12,
          textAlign: 'center',
          verticalAlign: 'middle',
        },
      } : {}),
    });
  }

  // 4. Sidebar Panels / Insights Widget (drawn by Excalidraw)
  const sideX = startX + numCols * (colWidth + colGap) + 20;
  let sideY = startY + 145;

  if (context.insights && context.insights.length > 0) {
    for (const insight of context.insights) {
      const insightBg = insight.kind === 'decision' ? '#f0fdf4' : (insight.kind === 'warning' ? '#fffbeb' : '#f8fafc');
      const insightStroke = insight.kind === 'decision' ? '#16a34a' : (insight.kind === 'warning' ? '#d97706' : '#64748b');

      skeletons.push({
        type: 'rectangle',
        x: sideX,
        y: sideY,
        width: 320,
        height: 130,
        backgroundColor: insightBg,
        strokeColor: insightStroke,
        fillStyle: 'solid',
        roundness: { type: 3 },
        roughness: 1,
        strokeWidth: 1.5,
        label: {
          text: `[${insight.kind.toUpperCase()}] ${insight.title}\n\n${insight.content}`,
          fontSize: 12,
          textAlign: 'left',
          verticalAlign: 'middle',
        },
      });
      sideY += 145;
    }
  }

  // 5. Context Stats & Metrics Widget (drawn by Excalidraw)
  skeletons.push({
    type: 'rectangle',
    x: sideX,
    y: sideY,
    width: 320,
    height: 150,
    backgroundColor: '#f8fafc',
    strokeColor: '#475569',
    fillStyle: 'solid',
    roundness: { type: 3 },
    roughness: 1,
    strokeWidth: 1.5,
    label: {
      text: (
        `DIORAMA VISUAL CONTEXT WIDGET\n\n` +
        `• Diagram Type: ${context.diagramType}\n` +
        `• Active Nodes: ${context.nodes.length}\n` +
        `• Connections: ${context.connections.length}\n` +
        `• Domain Groups: ${context.groups.length}\n\n` +
        'Tip: Ask AI to add components, connect services, or re-structure architecture.'
      ),
      fontSize: 12,
      textAlign: 'left',
      verticalAlign: 'middle',
    },
  });
  sideY += 165;

  // 6. Live AI Agent & Model Status Widget (drawn by Excalidraw)
  skeletons.push({
    type: 'rectangle',
    x: sideX,
    y: sideY,
    width: 320,
    height: 110,
    backgroundColor: '#0f172a',
    strokeColor: '#38bdf8',
    fillStyle: 'solid',
    roundness: { type: 3 },
    roughness: 0,
    strokeWidth: 1.5,
    label: {
      text: (
        'AGENT WIDGET: ACTIVE\n\n' +
        '• Engine: OpenRouter\n' +
        '• Stream: WebSocket Realtime Sync\n' +
        `• Nodes: ${context.nodes.length} | Connections: ${context.connections.length}`
      ),
      fontSize: 12,
      textAlign: 'left',
      verticalAlign: 'middle',
    },
  });

  return convertToExcalidrawElements(skeletons as ExcalidrawSkeleton);
}
