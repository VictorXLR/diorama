import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { ChatPanel } from '@/components/ChatPanel';
import { HeaderNav } from '@/components/HeaderNav';
import { ResizeHandle } from '@/components/ResizeHandle';
import { Whiteboard } from '@/components/Whiteboard';
import { MAX_CHAT_WIDTH, MIN_CHAT_WIDTH, sortConversations, useWorkspaceStore } from '@/lib/store';
import { convertServerWhiteboardElements } from '@/lib/whiteboardGenerator';
import type { WhiteboardElements } from '@/lib/whiteboardGenerator';
import type {
  AgentStatus,
  ChatMessage,
  ConnectionAckMessage,
  ConnectionState,
  ContextUpdateMessage,
  ExcalidrawSkeletonElement,
  ServerMessage,
} from '@/types/context';

// Default to the origin that served the app, so the built bundle talks to
// whatever host/port is serving it. Override with VITE_API_BASE_URL / VITE_WS_URL
// for split deployments (or the Vite dev server, which proxies to the backend).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? window.location.origin;
const WEBSOCKET_URL = import.meta.env.VITE_WS_URL ?? `${API_BASE_URL.replace(/^http/, 'ws').replace(/\/$/, '')}/ws`;

const EMPTY_ELEMENTS: WhiteboardElements = [];
const EMPTY_MESSAGES: ChatMessage[] = [];

function getTimestamp(): string {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function buildWelcomeMessage(): ChatMessage {
  return {
    id: 'workspace-welcome',
    sender: 'agent',
    content:
      'Welcome to Diorama. Tell me what to draw or change on the whiteboard and I will keep the conversation and canvas in sync.',
    timestamp: getTimestamp(),
    suggestions: ['Sketch a service architecture', 'Draw a product workflow', 'Illustrate a concept'],
  };
}

function parseServerMessage(data: unknown): ServerMessage | null {
  if (!data || typeof data !== 'object' || !('type' in data)) {
    return null;
  }

  return data as ServerMessage;
}

function normalizeAgentStatus(status: string): AgentStatus {
  switch (status) {
    case 'idle':
    case 'thinking':
    case 'analyzing_context':
    case 'generating_visual':
    case 'syncing_whiteboard':
      return status;
    default:
      return 'working';
  }
}

interface SessionUiState {
  conversationId: string | null;
  connection: ConnectionState;
  agent: AgentStatus;
}

export function App(): React.JSX.Element {
  const socketRef = useRef<WebSocket | null>(null);
  const excalidrawApiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  // Keyed by conversation so switching conversations implicitly resets to "connecting / idle".
  const [sessionUi, setSessionUi] = useState<SessionUiState>({
    conversationId: null,
    connection: 'connecting',
    agent: 'idle',
  });

  const theme = useWorkspaceStore((state) => state.theme);
  const toggleTheme = useWorkspaceStore((state) => state.toggleTheme);
  const chatWidth = useWorkspaceStore((state) => state.chatWidth);
  const setChatWidth = useWorkspaceStore((state) => state.setChatWidth);
  const activeConversationId = useWorkspaceStore((state) => state.activeConversationId);
  const activeConversation = useWorkspaceStore((state) =>
    state.activeConversationId ? state.conversations[state.activeConversationId] : undefined,
  );
  const conversationMap = useWorkspaceStore((state) => state.conversations);
  const conversations = useMemo(() => sortConversations(conversationMap), [conversationMap]);
  const createConversation = useWorkspaceStore((state) => state.createConversation);
  const selectConversation = useWorkspaceStore((state) => state.selectConversation);
  const deleteConversation = useWorkspaceStore((state) => state.deleteConversation);
  const renameConversationId = useWorkspaceStore((state) => state.renameConversationId);
  const updateConversation = useWorkspaceStore((state) => state.updateConversation);
  const appendStoredMessage = useWorkspaceStore((state) => state.appendMessage);
  const mergeFiles = useWorkspaceStore((state) => state.mergeFiles);
  // Element ids to flash on the board; a fresh array each time so re-highlighting the same ids works.
  const [highlightIds, setHighlightIds] = useState<string[] | null>(null);

  const connectionState: ConnectionState =
    sessionUi.conversationId === activeConversationId ? sessionUi.connection : 'connecting';
  const agentStatus: AgentStatus = sessionUi.conversationId === activeConversationId ? sessionUi.agent : 'idle';

  const setAgentStatus = useCallback((agent: AgentStatus): void => {
    setSessionUi((previous) => ({ ...previous, agent }));
  }, []);

  // Apply the persisted theme to <html> so Tailwind's `dark:` variant kicks in.
  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
  }, [theme]);

  // Always have an active conversation to talk to.
  useEffect(() => {
    if (!activeConversationId) {
      createConversation();
    }
  }, [activeConversationId, createConversation]);

  const applyVisualElements = useCallback(
    (conversationId: string, elements?: ExcalidrawSkeletonElement[]): void => {
      if (elements) {
        updateConversation(conversationId, { whiteboardElements: convertServerWhiteboardElements(elements) });
      }
    },
    [updateConversation],
  );

  const applyConnectionAck = useCallback(
    (conversationId: string, message: ConnectionAckMessage): void => {
      // The server may have minted a different id (e.g. it restarted); keep the store in sync.
      const serverId = message.sessionId || conversationId;
      renameConversationId(conversationId, serverId);

      const stored = useWorkspaceStore.getState().conversations[serverId];
      const serverMessages = message.initialMessages ?? [];
      const hasServerHistory = serverMessages.length > 0;
      const hasLocalHistory = (stored?.messages.length ?? 0) > 0;

      if (hasServerHistory) {
        updateConversation(serverId, {
          context: message.initialContext ?? null,
          messages: serverMessages,
        });
        if (message.files) {
          mergeFiles(serverId, message.files);
        }
        applyVisualElements(serverId, message.visualElements);
      } else if (!hasLocalHistory) {
        updateConversation(serverId, { context: null, messages: [buildWelcomeMessage()] });
        applyVisualElements(serverId, message.visualElements);
      }
      // Otherwise the server has forgotten this session but we still have it locally: keep ours.

      setSessionUi({ conversationId: serverId, connection: 'connected', agent: 'idle' });
    },
    [applyVisualElements, mergeFiles, renameConversationId, updateConversation],
  );

  const applyContextUpdate = useCallback(
    (conversationId: string, message: ContextUpdateMessage): void => {
      if (message.context !== undefined) {
        updateConversation(conversationId, { context: message.context ?? null });
      }
      // Files must land before the elements that reference them.
      if (message.files) {
        mergeFiles(conversationId, message.files);
      }
      applyVisualElements(conversationId, message.visualElements);
      if (message.changedElementIds && message.changedElementIds.length > 0) {
        setHighlightIds([...message.changedElementIds]);
      }
    },
    [applyVisualElements, mergeFiles, updateConversation],
  );

  useEffect(() => {
    if (!activeConversationId) {
      return;
    }
    const conversationId = activeConversationId;

    const socket = new WebSocket(`${WEBSOCKET_URL}/${encodeURIComponent(conversationId)}`);
    socketRef.current = socket;

    const markDisconnected = (): void => {
      const liveId = useWorkspaceStore.getState().activeConversationId ?? conversationId;
      setSessionUi({ conversationId: liveId, connection: 'disconnected', agent: 'idle' });
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      let parsedData: unknown;

      try {
        parsedData = JSON.parse(event.data);
      } catch {
        return;
      }

      const message = parseServerMessage(parsedData);
      if (!message) {
        return;
      }

      // After the ack the id may have been renamed; always resolve the live one.
      const liveId = useWorkspaceStore.getState().activeConversationId ?? conversationId;

      switch (message.type) {
        case 'connection_ack':
          applyConnectionAck(conversationId, message);
          break;
        case 'agent_status':
          setAgentStatus(normalizeAgentStatus(message.status));
          break;
        case 'context_update':
          applyContextUpdate(liveId, message);
          break;
        case 'agent_message':
          appendStoredMessage(liveId, message);
          break;
        case 'error':
          appendStoredMessage(liveId, {
            id: `error-${Date.now()}`,
            sender: 'system',
            content: message.message,
            timestamp: getTimestamp(),
          });
          setAgentStatus('idle');
          break;
        default:
          break;
      }
    };

    socket.onerror = markDisconnected;
    socket.onclose = markDisconnected;

    return () => {
      // Detach first so the deliberate close below does not flag the *next* conversation as offline.
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
      socketRef.current = null;
    };
  }, [activeConversationId, appendStoredMessage, applyConnectionAck, applyContextUpdate, setAgentStatus]);

  const sendSocketMessage = useCallback((message: object): boolean => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }

    socketRef.current.send(JSON.stringify(message));
    return true;
  }, []);

  const handleSendMessage = useCallback(
    (text: string): void => {
      if (!activeConversationId) {
        return;
      }
      // Ship the live scene (including the user's own edits), the current selection and the theme so
      // the agent patches what is actually on the board and can resolve "this" / "make it bigger".
      const api = excalidrawApiRef.current;
      const sceneElements = api?.getSceneElements() ?? [];
      const selectedElementIds = Object.keys(api?.getAppState().selectedElementIds ?? {});
      const files = useWorkspaceStore.getState().conversations[activeConversationId]?.files ?? {};
      if (
        !sendSocketMessage({
          type: 'user_message',
          content: text,
          visualElements: sceneElements,
          files,
          selectedElementIds,
          theme,
        })
      ) {
        return;
      }

      appendStoredMessage(activeConversationId, {
        id: `user-${Date.now()}`,
        sender: 'user',
        content: text,
        timestamp: getTimestamp(),
      });
      setAgentStatus('thinking');
    },
    [activeConversationId, appendStoredMessage, sendSocketMessage, setAgentStatus, theme],
  );

  const handleRevertTurn = useCallback(
    (turnId: string): void => {
      if (turnId && sendSocketMessage({ type: 'revert_turn', turnId })) {
        setAgentStatus('working');
      }
    },
    [sendSocketMessage, setAgentStatus],
  );

  const handleShowOnBoard = useCallback((elementIds: string[]): void => {
    const api = excalidrawApiRef.current;
    if (!api || elementIds.length === 0) {
      return;
    }
    const wanted = new Set(elementIds);
    const targets = api.getSceneElements().filter((element) => wanted.has(element.id));
    if (targets.length > 0) {
      try {
        api.scrollToContent(targets, { animate: true, duration: 350, fitToContent: true });
      } catch {
        api.scrollToContent(targets);
      }
    }
    setHighlightIds([...elementIds]);
  }, []);

  const handleResetWorkspace = useCallback((): void => {
    if (!activeConversationId) {
      return;
    }
    updateConversation(activeConversationId, {
      context: null,
      messages: EMPTY_MESSAGES,
      whiteboardElements: EMPTY_ELEMENTS,
      files: {},
      title: 'New conversation',
    });
    if (sendSocketMessage({ type: 'reset_session' })) {
      setAgentStatus('working');
    }
  }, [activeConversationId, sendSocketMessage, setAgentStatus, updateConversation]);

  const handleClearBoard = useCallback((): void => {
    if (activeConversationId) {
      updateConversation(activeConversationId, { whiteboardElements: EMPTY_ELEMENTS });
    }
  }, [activeConversationId, updateConversation]);

  const handleCreateConversation = useCallback((): void => {
    createConversation();
  }, [createConversation]);

  const handleApiReady = useCallback((api: ExcalidrawImperativeAPI): void => {
    excalidrawApiRef.current = api;
  }, []);

  const context = activeConversation?.context ?? null;
  const messages = activeConversation?.messages ?? EMPTY_MESSAGES;
  const whiteboardElements = activeConversation?.whiteboardElements ?? EMPTY_ELEMENTS;
  const files = activeConversation?.files;
  const workspaceTitle = context?.title ?? activeConversation?.title ?? 'New visual context';

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-slate-50 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <HeaderNav
        connectionState={connectionState}
        onClearBoard={handleClearBoard}
        onToggleTheme={toggleTheme}
        theme={theme}
        workspaceTitle={workspaceTitle}
      />

      <main className="flex min-h-0 flex-1 overflow-hidden">
        <Whiteboard
          elements={whiteboardElements}
          files={files}
          highlightIds={highlightIds}
          onApiReady={handleApiReady}
          onClearBoard={handleClearBoard}
          theme={theme}
          title={workspaceTitle}
        />
        <ResizeHandle maxWidth={MAX_CHAT_WIDTH} minWidth={MIN_CHAT_WIDTH} onResize={setChatWidth} width={chatWidth} />
        <div className="h-full shrink-0" style={{ width: chatWidth }}>
          <ChatPanel
            activeConversationId={activeConversationId}
            agentStatus={agentStatus}
            contextTitle={context?.title}
            conversations={conversations}
            isConnected={connectionState === 'connected'}
            messages={messages}
            onCreateConversation={handleCreateConversation}
            onDeleteConversation={deleteConversation}
            onResetWorkspace={handleResetWorkspace}
            onSelectConversation={selectConversation}
            onSendMessage={handleSendMessage}
            onShowOnBoard={handleShowOnBoard}
            onRevertTurn={handleRevertTurn}
          />
        </div>
      </main>
    </div>
  );
}

export default App;
