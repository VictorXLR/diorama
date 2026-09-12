import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowRight, Bot, ChevronDown, ChevronRight, Compass, Crosshair, FileText, HelpCircle, Network, RefreshCw, Send, Sparkles, Undo2, User } from 'lucide-react';
import { ConversationMenu } from '@/components/ConversationMenu';
import type { Conversation } from '@/lib/store';
import type { AgentStatus, ChatMessage, FileChange } from '@/types/context';

interface ChatPanelProps {
  activeConversationId: string | null;
  agentStatus: AgentStatus;
  contextTitle: string | undefined;
  conversations: Conversation[];
  isConnected: boolean;
  messages: ChatMessage[];
  onCreateConversation: () => void;
  onDeleteConversation: (id: string) => void;
  onResetWorkspace: () => void;
  onSelectConversation: (id: string) => void;
  onSendMessage: (text: string) => void;
  /** Scroll the board to (and briefly highlight) the elements a turn touched. */
  onShowOnBoard?: (elementIds: string[]) => void;
  /** Undo everything an agent turn did to the board. */
  onRevertTurn?: (turnId: string) => void;
}

function getStatusMessage(agentStatus: AgentStatus): string {
  const statusMessages: Record<Exclude<AgentStatus, 'idle'>, string> = {
    thinking: 'Reading your request...',
    analyzing_context: 'Identifying concepts and relationships...',
    generating_visual: 'Structuring the visual model...',
    syncing_whiteboard: 'Updating the whiteboard...',
    working: 'Working on the board...',
  };

  return statusMessages[agentStatus as Exclude<AgentStatus, 'idle'>];
}

function diffLineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return 'text-slate-400 dark:text-slate-500';
  }
  if (line.startsWith('+')) {
    return 'text-emerald-700 dark:text-emerald-400';
  }
  if (line.startsWith('-')) {
    return 'text-rose-700 dark:text-rose-400';
  }
  if (line.startsWith('@@')) {
    return 'text-indigo-600 dark:text-indigo-400';
  }
  return 'text-slate-600 dark:text-slate-300';
}

function FileChangeRow({ change }: { change: FileChange }): React.JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const hasDiff = change.diff.trim().length > 0;

  let chevron: React.JSX.Element;
  if (!hasDiff) {
    chevron = <span className="w-3" />;
  } else if (expanded) {
    chevron = <ChevronDown className="h-3 w-3 shrink-0 text-slate-400" />;
  } else {
    chevron = <ChevronRight className="h-3 w-3 shrink-0 text-slate-400" />;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
      <button
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
        disabled={!hasDiff}
        onClick={() => setExpanded((value) => !value)}
        type="button"
      >
        {chevron}
        <FileText className="h-3 w-3 shrink-0 text-slate-400" />
        <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-slate-700 dark:text-slate-200">
          {change.path}
        </span>
        <span className="shrink-0 rounded-full border border-slate-200 px-1.5 text-[10px] text-slate-500 dark:border-slate-600 dark:text-slate-400">
          {change.change === 'created' ? 'new' : 'edit'}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-emerald-600 dark:text-emerald-400">
          +{change.additions}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-rose-600 dark:text-rose-400">
          -{change.deletions}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {expanded && hasDiff && (
          <motion.div
            animate={{ height: 'auto', opacity: 1 }}
            className="overflow-hidden border-t border-slate-200 dark:border-slate-700"
            exit={{ height: 0, opacity: 0 }}
            initial={{ height: 0, opacity: 0 }}
          >
            <pre className="max-h-64 overflow-auto bg-slate-50 p-2 font-mono text-[10px] leading-relaxed dark:bg-slate-950">
              {change.diff.split('\n').map((line, index) => (
                <div className={diffLineClass(line)} key={`${index}-${line}`}>
                  {line || ' '}
                </div>
              ))}
            </pre>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function ChatPanel({
  activeConversationId,
  agentStatus,
  contextTitle,
  conversations,
  isConnected,
  messages,
  onCreateConversation,
  onDeleteConversation,
  onResetWorkspace,
  onSelectConversation,
  onSendMessage,
  onShowOnBoard,
  onRevertTurn,
}: ChatPanelProps): React.JSX.Element {
  const [inputText, setInputText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const canSendMessage = Boolean(inputText.trim()) && agentStatus === 'idle' && isConnected;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentStatus, messages]);

  const submitMessage = (): void => {
    const message = inputText.trim();
    if (!message || !canSendMessage) {
      return;
    }

    onSendMessage(message);
    setInputText('');
  };

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    submitMessage();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submitMessage();
    }
  };

  return (
    <aside className="flex h-full min-w-0 flex-col border-l border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="flex select-none items-center justify-between border-b border-slate-100 bg-slate-50/60 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/60">
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-sm shadow-indigo-200 dark:shadow-none">
            <Bot className="h-4 w-4" />
            <span
              className={`absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white dark:border-slate-900 ${isConnected ? 'bg-emerald-500' : 'bg-slate-400'}`}
            />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">Diorama</span>
              <span className="rounded-full border border-indigo-200 bg-indigo-50 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950 dark:text-indigo-300">
                {isConnected ? 'Connected' : 'Connecting'}
              </span>
            </div>
            {contextTitle && (
              <div className="flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400">
                <Network className="h-3 w-3 shrink-0 text-slate-400" />
                <span className="max-w-[180px] truncate">{contextTitle}</span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1">
          <ConversationMenu
            activeConversationId={activeConversationId}
            conversations={conversations}
            onCreate={onCreateConversation}
            onDelete={onDeleteConversation}
            onSelect={onSelectConversation}
          />
          <button
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            disabled={!isConnected}
            onClick={onResetWorkspace}
            title="Reset this conversation"
            type="button"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm leading-relaxed">
        {!isConnected && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
            Connecting to the Diorama server. The workspace will synchronize when the session is ready.
          </div>
        )}

        <AnimatePresence initial={false}>
          {messages.map((message) => {
            const isUserMessage = message.sender === 'user';
            const isAgentMessage = message.sender === 'agent';
            let messageClass: string;
            if (isUserMessage) {
              messageClass = 'rounded-br-none bg-indigo-600 text-white';
            } else if (isAgentMessage) {
              messageClass =
                'rounded-bl-none border border-slate-200/60 bg-slate-100 text-slate-800 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100';
            } else {
              messageClass =
                'rounded-bl-none border border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200';
            }

            return (
              <motion.div
                animate={{ opacity: 1, scale: 1, y: 0 }}
                className={`flex gap-2.5 ${isUserMessage ? 'justify-end' : 'justify-start'}`}
                exit={{ opacity: 0, scale: 0.95 }}
                initial={{ opacity: 0, scale: 0.98, y: 10 }}
                key={message.id}
                transition={{ duration: 0.2 }}
              >
                {isAgentMessage && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                    <Sparkles className="h-3.5 w-3.5" />
                  </div>
                )}

                <div className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 shadow-sm ${messageClass}`}>
                  <p className="break-words whitespace-pre-wrap">{message.content}</p>

                  {message.visualUpdate && (
                    <motion.div
                      animate={{ height: 'auto', opacity: 1 }}
                      className="mt-2.5 flex items-start gap-1.5 rounded-lg border-t border-slate-200/80 bg-white/70 px-2.5 py-1.5 text-xs text-indigo-900 dark:border-slate-700 dark:bg-slate-900/60 dark:text-indigo-200"
                      initial={{ height: 0, opacity: 0 }}
                    >
                      <Compass className="mt-0.5 h-3.5 w-3.5 shrink-0 text-indigo-600 dark:text-indigo-400" />
                      <div className="min-w-0 flex-1">
                        <span className="font-medium text-indigo-700 dark:text-indigo-300">Whiteboard updated</span>
                        <div className="text-[11px] text-slate-600 dark:text-slate-400">{message.visualUpdate.summary}</div>
                        {(message.changedElementIds?.length || message.turnId) && (
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {message.changedElementIds && message.changedElementIds.length > 0 && onShowOnBoard && (
                              <button
                                className="flex items-center gap-1 rounded-md border border-indigo-200 bg-white px-2 py-0.5 text-[11px] text-indigo-700 transition-colors hover:bg-indigo-50 dark:border-indigo-800 dark:bg-slate-900 dark:text-indigo-300 dark:hover:bg-indigo-950"
                                onClick={() => onShowOnBoard(message.changedElementIds ?? [])}
                                title="Highlight these changes on the board"
                                type="button"
                              >
                                <Crosshair className="h-3 w-3" />
                                Show on board
                              </button>
                            )}
                            {message.turnId && onRevertTurn && (
                              <button
                                className="flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2 py-0.5 text-[11px] text-slate-600 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-rose-800 dark:hover:bg-rose-950 dark:hover:text-rose-300"
                                disabled={agentStatus !== 'idle' || !isConnected}
                                onClick={() => onRevertTurn(message.turnId ?? '')}
                                title="Undo this change on the board"
                                type="button"
                              >
                                <Undo2 className="h-3 w-3" />
                                Revert
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </motion.div>
                  )}

                  {message.fileChanges && message.fileChanges.length > 0 && (
                    <div className="mt-2.5 space-y-1.5 border-t border-slate-200/60 pt-2 dark:border-slate-700">
                      <span className="flex items-center gap-1 text-[10px] font-semibold tracking-wider text-emerald-600 uppercase dark:text-emerald-400">
                        <FileText className="h-3 w-3" />
                        Files changed ({message.fileChanges.length})
                      </span>
                      <div className="space-y-1">
                        {message.fileChanges.map((change) => (
                          <FileChangeRow change={change} key={`${message.id}-${change.path}`} />
                        ))}
                      </div>
                    </div>
                  )}

                  {message.questions && message.questions.length > 0 && (
                    <div className="mt-2.5 space-y-1.5 border-t border-slate-200/60 pt-2 dark:border-slate-700">
                      <span className="flex items-center gap-1 text-[10px] font-semibold tracking-wider text-amber-600 uppercase dark:text-amber-400">
                        <HelpCircle className="h-3 w-3" />
                        Quick answers
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {message.questions.map((question) => (
                          <motion.button
                            className="flex items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-left text-[11px] text-amber-800 transition-all hover:border-amber-300 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200 dark:hover:border-amber-700"
                            disabled={agentStatus !== 'idle' || !isConnected}
                            key={question}
                            onClick={() => onSendMessage(question)}
                            type="button"
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                          >
                            <span>{question}</span>
                          </motion.button>
                        ))}
                      </div>
                    </div>
                  )}

                  {message.suggestions && message.suggestions.length > 0 && (
                    <div className="mt-2.5 space-y-1.5 border-t border-slate-200/60 pt-2 dark:border-slate-700">
                      <span className="block text-[10px] font-semibold tracking-wider text-slate-400 uppercase">
                        Suggested next steps
                      </span>
                      <div className="flex flex-wrap gap-1">
                        {message.suggestions.map((suggestion) => (
                          <motion.button
                            className="flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-left text-[11px] text-slate-700 transition-all hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:border-indigo-700 dark:hover:bg-indigo-950 dark:hover:text-indigo-300"
                            disabled={agentStatus !== 'idle' || !isConnected}
                            key={suggestion}
                            onClick={() => onSendMessage(suggestion)}
                            type="button"
                            whileHover={{ scale: 1.02 }}
                            whileTap={{ scale: 0.98 }}
                          >
                            <span>{suggestion}</span>
                            <ArrowRight className="h-2.5 w-2.5 text-slate-400" />
                          </motion.button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {isUserMessage && (
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-200">
                    <User className="h-3.5 w-3.5" />
                  </div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {agentStatus !== 'idle' && (
          <motion.div
            animate={{ opacity: 1, y: 0 }}
            className="flex w-fit items-center gap-2 rounded-xl border border-slate-200/70 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400"
            exit={{ opacity: 0 }}
            initial={{ opacity: 0, y: 5 }}
          >
            <div className="flex gap-1">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" style={{ animationDelay: '0.15s' }} />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-indigo-600" style={{ animationDelay: '0.3s' }} />
            </div>
            <span>{getStatusMessage(agentStatus)}</span>
          </motion.div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <form className="border-t border-slate-200/80 bg-white p-3 dark:border-slate-800 dark:bg-slate-900" onSubmit={handleSubmit}>
        <div className="relative flex items-center rounded-xl border border-slate-200 bg-slate-50 transition-all focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:focus-within:ring-indigo-950">
          <textarea
            className="min-h-[38px] max-h-24 flex-1 resize-none bg-transparent px-3 py-2 text-sm text-slate-800 placeholder-slate-400 focus:outline-none dark:text-slate-100 dark:placeholder-slate-500"
            disabled={agentStatus !== 'idle' || !isConnected}
            onChange={(event) => setInputText(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isConnected ? 'Describe what you want to draw or change on the board...' : 'Connecting to server...'}
            rows={1}
            value={inputText}
          />
          <button
            className="m-1 rounded-lg bg-indigo-600 p-2 text-white shadow-xs transition-colors hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400 dark:disabled:bg-slate-700 dark:disabled:text-slate-500"
            disabled={!canSendMessage}
            title="Send message"
            type="submit"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="mt-1 flex items-center justify-between px-1 text-[10px] text-slate-400 dark:text-slate-500">
          <span>Enter to send · Shift+Enter for a new line</span>
          <span>Chat and canvas stay synchronized</span>
        </div>
      </form>
    </aside>
  );
}

export default ChatPanel;
