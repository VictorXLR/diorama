import { useEffect, useRef, useState } from 'react';
import { Check, History, MessageSquarePlus, Trash2 } from 'lucide-react';
import type { Conversation } from '@/lib/store';

interface ConversationMenuProps {
  activeConversationId: string | null;
  conversations: Conversation[];
  onCreate: () => void;
  onDelete: (id: string) => void;
  onSelect: (id: string) => void;
}

function formatRelative(timestamp: number): string {
  const diffMinutes = Math.round((Date.now() - timestamp) / 60_000);
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return new Date(timestamp).toLocaleDateString();
}

export function ConversationMenu({
  activeConversationId,
  conversations,
  onCreate,
  onDelete,
  onSelect,
}: ConversationMenuProps): React.JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handleClickOutside = (event: MouseEvent): void => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    const handleEscape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);

  return (
    <div className="relative flex items-center gap-1" ref={containerRef}>
      <button
        className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200"
        onClick={() => {
          setIsOpen(false);
          onCreate();
        }}
        title="New conversation"
        type="button"
      >
        <MessageSquarePlus className="h-4 w-4" />
      </button>
      <button
        aria-expanded={isOpen}
        aria-haspopup="menu"
        className={`rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800 dark:hover:text-slate-200 ${isOpen ? 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-200' : ''}`}
        onClick={() => setIsOpen((open) => !open)}
        title="Conversation history"
        type="button"
      >
        <History className="h-4 w-4" />
      </button>

      {isOpen && (
        <div
          className="absolute top-full right-0 z-30 mt-1 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900"
          role="menu"
        >
          <div className="border-b border-slate-100 px-3 py-2 text-[10px] font-semibold tracking-wider text-slate-400 uppercase dark:border-slate-800">
            Conversations
          </div>
          <ul className="max-h-80 overflow-y-auto py-1">
            {conversations.length === 0 && (
              <li className="px-3 py-3 text-xs text-slate-500">No saved conversations yet.</li>
            )}
            {conversations.map((conversation) => {
              const isActive = conversation.id === activeConversationId;
              return (
                <li className="group flex items-center gap-1 px-1" key={conversation.id}>
                  <button
                    className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-2 text-left text-xs transition-colors hover:bg-slate-100 dark:hover:bg-slate-800 ${isActive ? 'text-indigo-700 dark:text-indigo-300' : 'text-slate-700 dark:text-slate-200'}`}
                    onClick={() => {
                      onSelect(conversation.id);
                      setIsOpen(false);
                    }}
                    role="menuitem"
                    type="button"
                  >
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {isActive && <Check className="h-3.5 w-3.5" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{conversation.title}</span>
                      <span className="block text-[10px] text-slate-400">
                        {conversation.messages.length} messages · {formatRelative(conversation.updatedAt)}
                      </span>
                    </span>
                  </button>
                  <button
                    className="rounded-md p-1.5 text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-600 focus:opacity-100 dark:text-slate-600 dark:hover:bg-rose-950"
                    onClick={() => onDelete(conversation.id)}
                    title="Delete conversation"
                    type="button"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ConversationMenu;
