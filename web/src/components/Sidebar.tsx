import { useState } from 'react';
import type React from 'react';
import {
  Archive,
  ChevronDown,
  ChevronRight,
  FolderGit2,
  GitBranch,
  Layers,
  MessageSquare,
  MessageSquarePlus,
  Plus,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import type { Conversation } from '@/lib/store';

export interface SidebarProps {
  activeConversationId: string | null;
  conversations: Conversation[];
  isOpen: boolean;
  onClose: () => void;
  onCreateConversation: () => void;
  onDeleteConversation: (id: string) => void;
  onSelectConversation: (id: string) => void;
  workspaceTitle?: string;
  activeTab: 'workspace' | 'landing';
  onNavigateLanding: () => void;
  onNavigateWorkspace: () => void;
}

function formatRelative(timestamp: number): string {
  const diffMinutes = Math.round((Date.now() - timestamp) / 60_000);
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(timestamp).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

export function Sidebar({
  activeConversationId,
  conversations,
  isOpen,
  onClose,
  onCreateConversation,
  onDeleteConversation,
  onSelectConversation,
  workspaceTitle,
  activeTab,
  onNavigateLanding,
  onNavigateWorkspace,
}: SidebarProps): React.JSX.Element {
  const [filterText, setFilterText] = useState('');
  const [isRecentExpanded, setIsRecentExpanded] = useState(true);

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(filterText.toLowerCase()) ||
    c.messages.some((m) => m.content.toLowerCase().includes(filterText.toLowerCase())),
  );

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-slate-900/60 backdrop-blur-xs md:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-slate-200 bg-white transition-all duration-200 ease-in-out md:static md:z-20 md:translate-x-0 dark:border-slate-800 dark:bg-slate-900/95 ${
          isOpen ? 'translate-x-0 shadow-2xl md:shadow-none' : '-translate-x-full md:hidden'
        }`}
      >
        {/* Workspace Brand / Navigation */}
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200/90 px-4 dark:border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-xs">
              <FolderGit2 className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <span className="block truncate text-xs font-semibold text-slate-800 dark:text-slate-100">
                {workspaceTitle ?? 'Diorama Workspace'}
              </span>
              <span className="block text-[10px] text-slate-500 dark:text-slate-400">Codebase Graph</span>
            </div>
          </div>
          <button
            aria-label="Close sidebar"
            className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:hidden dark:hover:bg-slate-800 dark:hover:text-slate-200"
            onClick={onClose}
            type="button"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Studio / Landing toggle tabs */}
        <div className="p-3 border-b border-slate-100 dark:border-slate-800/80">
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-800/60">
            <button
              className={`flex items-center justify-center gap-1.5 rounded-md py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'landing'
                  ? 'bg-white text-indigo-700 shadow-xs dark:bg-slate-700 dark:text-white'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
              }`}
              onClick={onNavigateLanding}
              type="button"
            >
              <GitBranch className="h-3.5 w-3.5" />
              <span>Overview</span>
            </button>
            <button
              className={`flex items-center justify-center gap-1.5 rounded-md py-1.5 text-xs font-medium transition-colors ${
                activeTab === 'workspace'
                  ? 'bg-white text-indigo-700 shadow-xs dark:bg-slate-700 dark:text-white'
                  : 'text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
              }`}
              onClick={onNavigateWorkspace}
              type="button"
            >
              <Layers className="h-3.5 w-3.5" />
              <span>Canvas</span>
            </button>
          </div>

          <button
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white shadow-xs transition-all hover:bg-indigo-500 active:scale-[0.98]"
            onClick={() => {
              onCreateConversation();
              onNavigateWorkspace();
            }}
            type="button"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>New Session</span>
          </button>
        </div>

        {/* Filter / Search input */}
        <div className="px-3 pt-3">
          <div className="relative flex items-center">
            <Search className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-slate-400" />
            <input
              className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pr-3 pl-8 text-xs text-slate-800 placeholder-slate-400 transition-colors focus:border-indigo-500 focus:bg-white focus:outline-hidden dark:border-slate-800 dark:bg-slate-950 dark:text-slate-100 dark:placeholder-slate-500 dark:focus:border-indigo-500"
              onChange={(e) => setFilterText(e.target.value)}
              placeholder="Search conversations..."
              type="text"
              value={filterText}
            />
          </div>
        </div>

        {/* Conversation List section */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 py-3">
          <div className="flex items-center justify-between px-2 py-1">
            <button
              className="flex items-center gap-1 text-[11px] font-semibold tracking-wider text-slate-500 uppercase hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              onClick={() => setIsRecentExpanded(!isRecentExpanded)}
              type="button"
            >
              {isRecentExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              <span>Sessions ({filteredConversations.length})</span>
            </button>
            <button
              aria-label="New chat session"
              className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
              onClick={() => {
                onCreateConversation();
                onNavigateWorkspace();
              }}
              title="New Session"
              type="button"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
            </button>
          </div>

          {isRecentExpanded && (
            <div className="mt-1 space-y-0.5">
              {filteredConversations.length === 0 ? (
                <div className="px-3 py-6 text-center text-xs text-slate-400">
                  <Archive className="mx-auto mb-1.5 h-6 w-6 opacity-40" />
                  <p>No conversations found</p>
                </div>
              ) : (
                filteredConversations.map((conversation) => {
                  const isActive =
                    conversation.id === activeConversationId && activeTab === 'workspace';
                  return (
                    <div
                      className={`group relative flex items-center justify-between rounded-lg px-2 py-2 text-xs transition-colors ${
                        isActive
                          ? 'bg-indigo-50/80 font-medium text-indigo-900 dark:bg-indigo-950/60 dark:text-indigo-200'
                          : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800/60'
                      }`}
                      key={conversation.id}
                    >
                      <button
                        className="flex min-w-0 flex-1 items-start gap-2 text-left"
                        onClick={() => {
                          onSelectConversation(conversation.id);
                          onNavigateWorkspace();
                        }}
                        type="button"
                      >
                        <MessageSquare
                          className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                            isActive
                              ? 'text-indigo-600 dark:text-indigo-400'
                              : 'text-slate-400 dark:text-slate-500'
                          }`}
                        />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-xs font-medium">{conversation.title}</p>
                          <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                            <span>{conversation.messages.length} msgs</span>
                            <span>·</span>
                            <span>{formatRelative(conversation.updatedAt)}</span>
                          </div>
                        </div>
                      </button>

                      <button
                        aria-label={`Delete conversation ${conversation.title}`}
                        className="rounded p-1 text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 dark:hover:bg-rose-950/60 dark:hover:text-rose-400"
                        onClick={() => onDeleteConversation(conversation.id)}
                        title="Delete conversation"
                        type="button"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>

        {/* Footer info badge */}
        <div className="border-t border-slate-200/90 p-3 text-[11px] text-slate-500 dark:border-slate-800 dark:text-slate-400">
          <div className="flex items-center justify-between">
            <span className="font-medium text-slate-700 dark:text-slate-300">Diorama Studio</span>
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono dark:bg-slate-800">
              AST + ReAct
            </span>
          </div>
        </div>
      </aside>
    </>
  );
}

export default Sidebar;
