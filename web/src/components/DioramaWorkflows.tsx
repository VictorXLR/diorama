import { useState } from 'react';
import {
  Boxes,
  Database,
  Loader2,
  MousePointerClick,
  Network,
  RefreshCw,
  Send,
  Workflow,
} from 'lucide-react';
import type { AgentStatus } from '@/types/context';

export interface DioramaWorkflow {
  id: string;
  title: string;
  description: string;
  icon: typeof Network;
  /** Prompt sent to the agent when run. */
  prompt: string;
}

/**
 * One-click Diorama engineering workflows surfaced directly on the Excalidraw
 * canvas, so the board can query the codebase without round-tripping through
 * the chat panel.
 */
const WORKFLOWS: DioramaWorkflow[] = [
  {
    id: 'connectivity',
    title: 'Map API connectivity',
    description: 'Connectors, endpoints, tables, and UI wiring on one board.',
    icon: Network,
    prompt:
      'Map how the APIs are connected in this codebase: external connectors (Supabase, Stripe, etc.), HTTP endpoints, database tables, and which UI surfaces call them. Draw the full connectivity map.',
  },
  {
    id: 'supabase',
    title: 'Zoom into Supabase',
    description: 'Tables, inferred columns, and the files touching each table.',
    icon: Database,
    prompt:
      'Zoom into the Supabase connection: show each table with its columns and operations, which files read or write it, and any rpc functions or storage buckets. Draw it on the whiteboard.',
  },
  {
    id: 'architecture',
    title: 'Visualize architecture',
    description: 'High-level modules, services, and how they depend on each other.',
    icon: Boxes,
    prompt:
      'Visualize the high-level architecture of this codebase: the main modules and services, what they depend on, and how data flows between them.',
  },
  {
    id: 'state',
    title: 'Trace state & data flow',
    description: 'State management, hooks, and request flow from UI to storage.',
    icon: Workflow,
    prompt:
      'Trace state and data flow in this codebase: which state management each UI surface uses, and how requests flow from the UI through endpoints down to storage. Draw the flow.',
  },
];

export interface DioramaWorkflowsProps {
  /** Sends a prompt to the agent as if typed in chat. */
  onRunWorkflow: (prompt: string) => void;
  /** Re-indexes the workspace and redraws the generated codebase map. */
  onRefreshCodebaseMap: () => void;
  agentStatus: AgentStatus;
  isConnected: boolean;
  /** Text of the elements currently selected on the canvas (empty when none). */
  selectedLabels: string[];
}

const BUSY_STATUSES: ReadonlySet<AgentStatus> = new Set([
  'thinking',
  'analyzing_context',
  'generating_visual',
  'syncing_whiteboard',
  'working',
]);

export function DioramaWorkflows({
  onRunWorkflow,
  onRefreshCodebaseMap,
  agentStatus,
  isConnected,
  selectedLabels,
}: DioramaWorkflowsProps): React.JSX.Element {
  const [isExpanded, setIsExpanded] = useState(true);
  const [quickQuery, setQuickQuery] = useState('');
  const isBusy = BUSY_STATUSES.has(agentStatus);
  const disabled = isBusy || !isConnected;
  const selectionSummary =
    selectedLabels.length > 0
      ? [selectedLabels.slice(0, 2).join(', '), selectedLabels.length > 2 ? '…' : null]
          .filter(Boolean)
          .join('')
      : 'Select elements on the canvas, then ask';

  /** Prompts fired with an active selection carry it so the agent can zoom in. */
  const runPrompt = (prompt: string): void => {
    if (disabled) {
      return;
    }
    if (selectedLabels.length > 0) {
      const quoted = selectedLabels.map((label) => `"${label}"`).join(', ');
      onRunWorkflow(`${prompt}\n\nThe user currently selected these board elements: ${quoted}. Focus on them.`);
    } else {
      onRunWorkflow(prompt);
    }
  };

  const handleQuickQuery = (): void => {
    const query = quickQuery.trim();
    if (!query || disabled) {
      return;
    }
    runPrompt(query);
    setQuickQuery('');
  };

  return (
    <div className="absolute bottom-4 left-3 z-10 w-64 rounded-xl border border-slate-200/90 bg-white/95 text-xs text-slate-700 shadow-sm backdrop-blur-md dark:border-slate-800 dark:bg-slate-900/95 dark:text-slate-200">
      <div className="flex items-center justify-between px-3 py-2">
        <div className="flex items-center gap-1.5 font-semibold text-slate-800 dark:text-slate-100">
          {isBusy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600 dark:text-indigo-400" />
          ) : (
            <Network className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
          )}
          <span>Diorama workflows</span>
        </div>
        {selectedLabels.length > 0 && (
          <span
            className="max-w-24 truncate rounded bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 dark:bg-indigo-950/80 dark:text-indigo-300"
            title={`Selected: ${selectedLabels.join(', ')}`}
          >
            {selectedLabels.length} selected
          </span>
        )}
        <button
          className="rounded px-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800 dark:hover:text-slate-200"
          onClick={() => setIsExpanded((expanded) => !expanded)}
          title={isExpanded ? 'Collapse workflows' : 'Expand workflows'}
          type="button"
        >
          {isExpanded ? '−' : '+'}
        </button>
      </div>

      {isExpanded && (
        <div className="flex flex-col gap-1 border-t border-slate-200 p-2 dark:border-slate-800">
          <button
            className="flex items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-indigo-950/60"
            disabled={disabled || selectedLabels.length === 0}
            key="explain-selection"
            onClick={() =>
              runPrompt(
                'Explain what the selected board elements represent in this codebase: what they are, how they connect to the rest of the system, and anything noteworthy about their implementation.',
              )
            }
            title={
              selectedLabels.length > 0
                ? `Ask about: ${selectedLabels.join(', ')}`
                : 'Select one or more elements on the canvas first'
            }
            type="button"
          >
            <MousePointerClick className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
            <span className="flex flex-col">
              <span className="font-medium text-slate-800 dark:text-slate-100">Explain selection</span>
              <span className="text-[10px] leading-snug text-slate-500 dark:text-slate-400">
                {selectionSummary}
              </span>
            </span>
          </button>

          {WORKFLOWS.map((workflow) => {
            const Icon = workflow.icon;
            return (
              <button
                className="group flex items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:bg-indigo-950/60"
                disabled={disabled}
                key={workflow.id}
                onClick={() => runPrompt(workflow.prompt)}
                title={workflow.description}
                type="button"
              >
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
                <span className="flex flex-col">
                  <span className="font-medium text-slate-800 dark:text-slate-100">{workflow.title}</span>
                  <span className="text-[10px] leading-snug text-slate-500 dark:text-slate-400">
                    {workflow.description}
                  </span>
                </span>
              </button>
            );
          })}

          <button
            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left font-medium text-slate-800 transition-colors hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-100 dark:hover:bg-indigo-950/60"
            disabled={disabled}
            onClick={onRefreshCodebaseMap}
            title="Re-index the workspace and redraw the codebase map"
            type="button"
          >
            <RefreshCw className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400" />
            <span>Refresh codebase map</span>
          </button>

          <div className="mt-1 border-t border-slate-200 pt-2 dark:border-slate-800">
            <div className="flex items-center gap-1.5">
              <input
                className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1.5 text-xs text-slate-800 placeholder:text-slate-400 focus:border-indigo-400 focus:outline-none disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
                disabled={disabled}
                onChange={(event) => setQuickQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    handleQuickQuery();
                  }
                }}
                placeholder={isConnected ? 'Ask about this codebase…' : 'Connecting…'}
                type="text"
                value={quickQuery}
              />
              <button
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-indigo-600 text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={disabled || quickQuery.trim().length === 0}
                onClick={handleQuickQuery}
                title="Send query to the Diorama agent"
                type="button"
              >
                <Send className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default DioramaWorkflows;
