import type React from 'react';
import {
  ArrowRight,
  Boxes,
  Database,
  GitBranch,
  MessageSquare,
  Network,
  Search,
  SquareTerminal,
  Undo2,
} from 'lucide-react';
import type { Conversation } from '@/lib/store';

export interface LandingPageProps {
  onOpenWorkspace: () => void;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  conversations: Conversation[];
  workspaceTitle: string | undefined;
  isConnected: boolean;
}

/* ------------------------------------------------------------------ */
/* Small schematics: each "zoom level" card carries a miniature of    */
/* the board it describes, drawn in plain SVG.                         */
/* ------------------------------------------------------------------ */

function FileMapSchematic(): React.JSX.Element {
  return (
    <svg className="h-20 w-full" viewBox="0 0 200 80" fill="none">
      <rect x="4" y="8" width="56" height="30" rx="3" stroke="#6366f1" strokeWidth="1.5" />
      <rect x="10" y="14" width="30" height="4" rx="2" fill="#6366f1" opacity="0.7" />
      <rect x="10" y="24" width="44" height="3" rx="1.5" fill="#334155" />
      <rect x="76" y="8" width="56" height="30" rx="3" stroke="#6366f1" strokeWidth="1.5" />
      <rect x="82" y="14" width="30" height="4" rx="2" fill="#6366f1" opacity="0.7" />
      <rect x="82" y="24" width="44" height="3" rx="1.5" fill="#334155" />
      <rect x="40" y="50" width="56" height="26" rx="3" stroke="#475569" strokeWidth="1.5" />
      <rect x="46" y="56" width="26" height="4" rx="2" fill="#475569" opacity="0.8" />
      <path d="M60 38 L60 50" stroke="#64748b" strokeWidth="1.5" strokeDasharray="3 3" />
      <path d="M60 50 L57 46 M60 50 L63 46" stroke="#64748b" strokeWidth="1.5" />
      <path d="M104 23 L132 23" stroke="#64748b" strokeWidth="1.5" />
      <path d="M132 23 L128 20 M132 23 L128 26" stroke="#64748b" strokeWidth="1.5" />
    </svg>
  );
}

function ArchitectureSchematic(): React.JSX.Element {
  return (
    <svg className="h-20 w-full" viewBox="0 0 200 80" fill="none">
      <rect x="8" y="12" width="44" height="34" rx="3" stroke="#10b981" strokeWidth="1.5" />
      <rect x="14" y="18" width="24" height="4" rx="2" fill="#10b981" opacity="0.8" />
      <rect x="14" y="28" width="32" height="3" rx="1.5" fill="#334155" />
      <rect x="78" y="12" width="44" height="34" rx="3" stroke="#818cf8" strokeWidth="1.5" />
      <rect x="84" y="18" width="24" height="4" rx="2" fill="#818cf8" opacity="0.8" />
      <rect x="84" y="28" width="32" height="3" rx="1.5" fill="#334155" />
      <rect x="148" y="12" width="44" height="34" rx="3" stroke="#fb7185" strokeWidth="1.5" />
      <rect x="154" y="18" width="24" height="4" rx="2" fill="#fb7185" opacity="0.8" />
      <rect x="154" y="28" width="32" height="3" rx="1.5" fill="#334155" />
      <path d="M52 29 L78 29" stroke="#64748b" strokeWidth="1.5" />
      <path d="M78 29 L74 26 M78 29 L74 32" stroke="#64748b" strokeWidth="1.5" />
      <path d="M122 29 L148 29" stroke="#64748b" strokeWidth="1.5" />
      <path d="M148 29 L144 26 M148 29 L144 32" stroke="#64748b" strokeWidth="1.5" />
      <text x="10" y="66" fill="#64748b" fontSize="9" fontFamily="monospace">data</text>
      <text x="80" y="66" fill="#64748b" fontSize="9" fontFamily="monospace">logic</text>
      <text x="152" y="66" fill="#64748b" fontSize="9" fontFamily="monospace">ui</text>
    </svg>
  );
}

function ConnectivitySchematic(): React.JSX.Element {
  return (
    <svg className="h-20 w-full" viewBox="0 0 200 80" fill="none">
      <rect x="6" y="10" width="52" height="22" rx="3" stroke="#10b981" strokeWidth="1.5" />
      <rect x="12" y="16" width="34" height="4" rx="2" fill="#10b981" opacity="0.8" />
      <rect x="6" y="40" width="52" height="22" rx="3" stroke="#10b981" strokeWidth="1.5" strokeDasharray="4 3" />
      <rect x="12" y="46" width="34" height="4" rx="2" fill="#10b981" opacity="0.5" />
      <rect x="74" y="25" width="52" height="22" rx="3" stroke="#38bdf8" strokeWidth="1.5" />
      <rect x="80" y="31" width="34" height="4" rx="2" fill="#38bdf8" opacity="0.8" />
      <rect x="142" y="25" width="52" height="22" rx="3" stroke="#fb7185" strokeWidth="1.5" />
      <rect x="148" y="31" width="34" height="4" rx="2" fill="#fb7185" opacity="0.8" />
      <path d="M58 51 L74 38" stroke="#64748b" strokeWidth="1.5" />
      <path d="M126 36 L142 36" stroke="#64748b" strokeWidth="1.5" />
      <path d="M142 36 L138 33 M142 36 L138 39" stroke="#64748b" strokeWidth="1.5" />
      <text x="8" y="76" fill="#64748b" fontSize="9" fontFamily="monospace">supabase · tables</text>
      <text x="76" y="20" fill="#64748b" fontSize="9" fontFamily="monospace">/api routes</text>
      <text x="144" y="20" fill="#64748b" fontSize="9" fontFamily="monospace">ui + state</text>
    </svg>
  );
}

const ZOOM_LEVELS = [
  {
    icon: Boxes,
    schematic: FileMapSchematic,
    title: 'File map',
    command: 'visualize_codebase',
    description:
      'One card per file, grouped by directory, arrows for imports. Parsed from the AST with tree-sitter — not a model guessing at structure.',
  },
  {
    icon: Network,
    schematic: ArchitectureSchematic,
    title: 'Architecture',
    command: 'component roles',
    description:
      'Files roll up into components by role — database, business logic, web service, UI — with weighted dependency edges and an environment panel.',
  },
  {
    icon: Database,
    schematic: ConnectivitySchematic,
    title: 'API connectivity',
    command: 'visualize_connectivity',
    description:
      'Zoom into how the system is wired: Supabase tables and their columns, HTTP endpoints, which UI files call them, and how state is held.',
  },
];

const REFLEXIVE_LOOP = [
  {
    icon: MessageSquare,
    title: 'Ask in plain language',
    description: '"How do orders reach the database?" or "Which files does the entry point depend on?"',
  },
  {
    icon: Search,
    title: 'The agent reads real code',
    description: 'It searches, reads, and runs your repository through confined tools — every claim is grounded in source.',
  },
  {
    icon: GitBranch,
    title: 'The board answers',
    description: 'Diagrams are derived from the index and drawn as live, editable Excalidraw elements — not screenshots.',
  },
  {
    icon: Undo2,
    title: 'Verify, edit, revert',
    description: 'Code edits arrive as diffs, commands return real exit codes, and any turn can be rolled back in one click.',
  },
];

const AGENT_TOOLS = [
  'read_file',
  'search_code',
  'index_codebase',
  'map_connectivity',
  'edit_file',
  'run_command',
];

function formatTimeAgo(timestamp: number): string {
  const diffMinutes = Math.round((Date.now() - timestamp) / 60_000);
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(timestamp).toLocaleDateString();
}

export function LandingPage({
  onOpenWorkspace,
  onNewConversation,
  onSelectConversation,
  conversations,
  workspaceTitle,
  isConnected,
}: LandingPageProps): React.JSX.Element {
  const recentConversations = conversations.slice(0, 4);

  return (
    <div className="flex h-full w-full flex-col overflow-y-auto bg-slate-950 text-slate-100 selection:bg-indigo-500/30 selection:text-indigo-200">
      {/* Blueprint grid backdrop */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b14_1px,transparent_1px),linear-gradient(to_bottom,#1e293b14_1px,transparent_1px)] bg-[size:32px_32px]" />
        <div className="absolute -top-32 left-1/2 h-72 w-[640px] -translate-x-1/2 rounded-full bg-indigo-500/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col px-6 py-10 md:px-10">
        {/* Top bar */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-indigo-500/40 bg-indigo-500/10">
              <Boxes className="h-4 w-4 text-indigo-400" />
            </div>
            <div>
              <span className="font-mono text-sm font-semibold tracking-tight text-white">diorama</span>
              <p className="text-[11px] text-slate-500">a visual workbench for real codebases</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-slate-800 bg-slate-900/80 px-3 py-1.5 text-[11px] sm:flex">
              <span className={`h-1.5 w-1.5 rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-amber-400'}`} />
              <span className="text-slate-400">{isConnected ? 'server connected' : 'connecting…'}</span>
            </div>
            <button
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-indigo-500"
              onClick={onOpenWorkspace}
              type="button"
            >
              Open workspace
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {/* Hero */}
        <div className="mt-14 md:mt-20">
          <code className="rounded-md border border-slate-800 bg-slate-900/80 px-3 py-1.5 font-mono text-xs text-emerald-400">
            $ diorama dev ./your-repo
          </code>

          <h1 className="mt-6 max-w-3xl text-4xl font-bold leading-tight tracking-tight text-white md:text-5xl">
            See how your codebase <span className="text-indigo-400">actually works.</span>
          </h1>

          <p className="mt-5 max-w-2xl text-base leading-relaxed text-slate-400">
            Diorama binds to a repository on disk, indexes it into a graph of files, symbols, and dependencies, and
            renders that graph on an interactive whiteboard. Then you ask technical questions in plain language — an
            agent with real code tools reads your source, draws the answer on the board, and can edit and verify the
            code it finds. The map comes from the AST, not from a model&apos;s guess.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <button
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-indigo-600/20 transition-colors hover:bg-indigo-500"
              onClick={onOpenWorkspace}
              type="button"
            >
              <SquareTerminal className="h-4 w-4" />
              Enter the workspace
              <ArrowRight className="h-4 w-4" />
            </button>
            <button
              className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900/80 px-5 py-3 text-sm font-semibold text-slate-300 transition-colors hover:border-slate-700 hover:text-white"
              onClick={onNewConversation}
              type="button"
            >
              <MessageSquare className="h-4 w-4 text-slate-500" />
              New conversation
            </button>
            {workspaceTitle && (
              <span className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 font-mono text-xs text-emerald-300">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                {workspaceTitle}
              </span>
            )}
          </div>
        </div>

        {/* Zoom levels */}
        <div className="mt-16">
          <h2 className="text-lg font-semibold text-white">Three levels of zoom</h2>
          <p className="mt-1 text-sm text-slate-500">
            The same index, rolled up three ways — from &quot;what files exist&quot; to &quot;how does a click become a
            query&quot;.
          </p>

          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
            {ZOOM_LEVELS.map((level) => {
              const Icon = level.icon;
              const Schematic = level.schematic;
              return (
                <div
                  className="flex flex-col rounded-xl border border-slate-800/90 bg-slate-900/50 p-5"
                  key={level.title}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="h-4 w-4 text-indigo-400" />
                    <h3 className="text-sm font-semibold text-slate-100">{level.title}</h3>
                  </div>
                  <div className="mt-4 rounded-lg border border-slate-800/70 bg-slate-950/60 px-3 py-2">
                    <Schematic />
                  </div>
                  <p className="mt-4 text-xs leading-relaxed text-slate-400">{level.description}</p>
                  <code className="mt-3 font-mono text-[10px] text-slate-600">{level.command}</code>
                </div>
              );
            })}
          </div>
        </div>

        {/* Reflexive loop */}
        <div className="mt-14">
          <h2 className="text-lg font-semibold text-white">The reflexive loop</h2>
          <p className="mt-1 text-sm text-slate-500">
            The board and the conversation are one surface. Every answer is drawn; every drawing can be questioned.
          </p>

          <div className="mt-6 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-slate-800 bg-slate-800 sm:grid-cols-2 lg:grid-cols-4">
            {REFLEXIVE_LOOP.map((step, index) => {
              const Icon = step.icon;
              return (
                <div className="bg-slate-900/60 p-5" key={step.title}>
                  <div className="flex items-center justify-between">
                    <Icon className="h-4 w-4 text-indigo-400" />
                    <span className="font-mono text-[10px] text-slate-600">0{index + 1}</span>
                  </div>
                  <h3 className="mt-3 text-sm font-semibold text-slate-100">{step.title}</h3>
                  <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{step.description}</p>
                </div>
              );
            })}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-slate-500">agent tools:</span>
            {AGENT_TOOLS.map((tool) => (
              <code
                className="rounded-md border border-slate-800 bg-slate-900/80 px-2 py-1 font-mono text-[10px] text-slate-400"
                key={tool}
              >
                {tool}()
              </code>
            ))}
          </div>
        </div>

        {/* Recent conversations */}
        {recentConversations.length > 0 && (
          <div className="mt-14">
            <h2 className="text-lg font-semibold text-white">Resume a session</h2>
            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {recentConversations.map((c) => (
                <button
                  className="group flex flex-col justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-left transition-colors hover:border-indigo-500/40 hover:bg-slate-900"
                  key={c.id}
                  onClick={() => onSelectConversation(c.id)}
                  type="button"
                >
                  <div>
                    <h3 className="truncate text-xs font-semibold text-slate-200 group-hover:text-indigo-300">
                      {c.title}
                    </h3>
                    <p className="mt-1 line-clamp-2 text-[11px] text-slate-500">
                      {c.messages.length > 0 && c.messages[c.messages.length - 1]
                        ? c.messages[c.messages.length - 1]?.content.slice(0, 80)
                        : 'No messages yet'}
                    </p>
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t border-slate-800/60 pt-2 text-[10px] text-slate-600">
                    <span>{c.messages.length} turns</span>
                    <span>{formatTimeAgo(c.updatedAt)}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="mt-auto flex items-center justify-between border-t border-slate-800/80 pt-6 text-[11px] text-slate-600">
          <span className="font-mono">diorama v0.1.0 · excalidraw + tree-sitter + agent tools</span>
          <div className="flex items-center gap-5">
            <button className="transition-colors hover:text-slate-300" onClick={onOpenWorkspace} type="button">
              workspace
            </button>
            <button className="transition-colors hover:text-slate-300" onClick={onNewConversation} type="button">
              new session
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LandingPage;
