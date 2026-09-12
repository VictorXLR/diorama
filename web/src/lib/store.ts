import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { WhiteboardElements } from '@/lib/whiteboardGenerator';
import type { CanvasFiles, ChatMessage, ContextVisualization } from '@/types/context';

export type Theme = 'light' | 'dark';

export interface Conversation {
  id: string;
  title: string;
  messages: ChatMessage[];
  context: ContextVisualization | null;
  whiteboardElements: WhiteboardElements;
  /** Image assets referenced by `image` elements. Persisted so boards survive reloads. */
  files: CanvasFiles;
  createdAt: number;
  updatedAt: number;
}

interface WorkspaceState {
  theme: Theme;
  chatWidth: number;
  activeConversationId: string | null;
  conversations: Record<string, Conversation>;

  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
  setChatWidth: (width: number) => void;

  createConversation: () => string;
  selectConversation: (id: string) => void;
  deleteConversation: (id: string) => void;
  /** Called when the server acknowledges a connection; the server may have assigned a new id. */
  renameConversationId: (fromId: string, toId: string) => void;
  updateConversation: (id: string, patch: Partial<Omit<Conversation, 'id' | 'createdAt'>>) => void;
  appendMessage: (id: string, message: ChatMessage) => void;
  /** Merge new/changed assets into a conversation's file map. */
  mergeFiles: (id: string, files: CanvasFiles) => void;
}

export const MIN_CHAT_WIDTH = 320;
export const MAX_CHAT_WIDTH = 900;
export const DEFAULT_CHAT_WIDTH = 420;

function newId(): string {
  return `sess-${crypto.randomUUID().replace(/-/g, '').slice(0, 8)}`;
}

function clampWidth(width: number): number {
  return Math.min(MAX_CHAT_WIDTH, Math.max(MIN_CHAT_WIDTH, width));
}

function buildConversation(id: string): Conversation {
  const now = Date.now();
  return {
    id,
    title: 'New conversation',
    messages: [],
    context: null,
    whiteboardElements: [],
    files: {},
    createdAt: now,
    updatedAt: now,
  };
}

function deriveTitle(conversation: Conversation, patch: Partial<Conversation>): string {
  if (patch.context?.title) {
    return patch.context.title;
  }
  if (conversation.title !== 'New conversation') {
    return conversation.title;
  }
  const firstUser = (patch.messages ?? conversation.messages).find((message) => message.sender === 'user');
  return firstUser ? firstUser.content.slice(0, 60) : conversation.title;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      theme: 'light',
      chatWidth: DEFAULT_CHAT_WIDTH,
      activeConversationId: null,
      conversations: {},

      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set((state) => ({ theme: state.theme === 'dark' ? 'light' : 'dark' })),
      setChatWidth: (width) => set({ chatWidth: clampWidth(width) }),

      createConversation: () => {
        const id = newId();
        set((state) => ({
          activeConversationId: id,
          conversations: { ...state.conversations, [id]: buildConversation(id) },
        }));
        return id;
      },

      selectConversation: (id) => {
        if (get().conversations[id]) {
          set({ activeConversationId: id });
        }
      },

      deleteConversation: (id) => {
        set((state) => {
          const remaining = { ...state.conversations };
          delete remaining[id];
          const nextActive =
            state.activeConversationId === id
              ? (Object.values(remaining).sort((a, b) => b.updatedAt - a.updatedAt)[0]?.id ?? null)
              : state.activeConversationId;
          return { conversations: remaining, activeConversationId: nextActive };
        });
      },

      renameConversationId: (fromId, toId) => {
        if (fromId === toId) {
          return;
        }
        set((state) => {
          const existing = state.conversations[fromId];
          if (!existing) {
            return state;
          }
          const conversations = { ...state.conversations };
          delete conversations[fromId];
          conversations[toId] = { ...existing, id: toId };
          return {
            conversations,
            activeConversationId: state.activeConversationId === fromId ? toId : state.activeConversationId,
          };
        });
      },

      updateConversation: (id, patch) => {
        set((state) => {
          const existing = state.conversations[id];
          if (!existing) {
            return state;
          }
          const updated: Conversation = {
            ...existing,
            ...patch,
            title: patch.title ?? deriveTitle(existing, patch),
            updatedAt: Date.now(),
          };
          return { conversations: { ...state.conversations, [id]: updated } };
        });
      },

      appendMessage: (id, message) => {
        const existing = get().conversations[id];
        if (!existing) {
          return;
        }
        get().updateConversation(id, { messages: [...existing.messages, message] });
      },

      mergeFiles: (id, files) => {
        const existing = get().conversations[id];
        if (!existing || Object.keys(files).length === 0) {
          return;
        }
        get().updateConversation(id, { files: { ...existing.files, ...files } });
      },
    }),
    {
      name: 'diorama-workspace',
      version: 2,
      migrate: (persisted) => {
        const state = persisted as Partial<WorkspaceState> | undefined;
        const conversations: Record<string, Conversation> = {};
        for (const [id, conversation] of Object.entries(state?.conversations ?? {})) {
          conversations[id] = { ...conversation, files: conversation.files ?? {} };
        }
        return { ...state, conversations } as WorkspaceState;
      },
      partialize: (state) => ({
        theme: state.theme,
        chatWidth: state.chatWidth,
        activeConversationId: state.activeConversationId,
        conversations: state.conversations,
      }),
    },
  ),
);

export function sortConversations(conversations: Record<string, Conversation>): Conversation[] {
  return Object.values(conversations).sort((a, b) => b.updatedAt - a.updatedAt);
}
