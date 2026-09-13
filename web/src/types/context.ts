export type NodeCategory =
  | 'client'
  | 'service'
  | 'gateway'
  | 'database'
  | 'queue'
  | 'storage'
  | 'external'
  | 'workflow_step'
  | 'concept'
  | 'custom';

export type DiagramType =
  | 'architecture'
  | 'flowchart'
  | 'context_map'
  | 'system_topology'
  | 'workflow';

export type ChatSender = 'user' | 'agent' | 'system';

export interface VisualUpdate {
  summary: string;
  elementsAdded: number;
}

/** A workspace file the agent created or edited during a turn. */
export interface FileChange {
  path: string;
  change: 'created' | 'modified';
  diff: string;
  additions: number;
  deletions: number;
}

export interface ChatMessage {
  id: string;
  sender: ChatSender;
  content: string;
  timestamp: string;
  visualUpdate?: VisualUpdate;
  suggestions?: string[];
  /** Clarifying questions the agent wants answered before (or instead of) drawing. */
  questions?: string[];
  /** Agent turn that produced this message; lets the user revert its board changes. */
  turnId?: string;
  /** Element ids the turn created or modified; used for highlight-on-hover. */
  changedElementIds?: string[];
  /** Workspace files the turn created or edited, with unified diffs. */
  fileChanges?: FileChange[];
}

/** A binary asset (image) referenced by an Excalidraw `image` element via `fileId`. */
export interface CanvasFile {
  mimeType: string;
  dataURL: string;
  created?: number;
}

export type CanvasFiles = Record<string, CanvasFile>;

export type AgentStatus =
  | 'idle'
  | 'thinking'
  | 'analyzing_context'
  | 'generating_visual'
  | 'syncing_whiteboard'
  | 'working';

export type ConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'disconnected';

export interface ContextNode {
  id: string;
  label: string;
  subtitle?: string;
  category: NodeCategory;
  description?: string;
  groupId?: string;
  tags?: string[];
  status?: string;
  metadata?: Record<string, unknown>;
}

export interface ContextConnection {
  id: string;
  fromNode: string;
  toNode: string;
  label?: string;
  style?: 'solid' | 'dashed' | 'dotted';
  bidirectional?: boolean;
}

export interface ContextGroup {
  id: string;
  title: string;
  description?: string;
  color?: string;
}

export interface ContextInsight {
  title: string;
  content: string;
  kind: 'info' | 'metric' | 'decision' | 'warning' | 'tip';
}

export interface ContextVisualization {
  id: string;
  title: string;
  summary: string;
  diagramType: DiagramType;
  groups: ContextGroup[];
  nodes: ContextNode[];
  connections: ContextConnection[];
  insights: ContextInsight[];
  tags: string[];
}

export interface ExcalidrawSkeletonElement {
  type: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  strokeColor?: string;
  backgroundColor?: string;
  fillStyle?: 'solid' | 'hachure' | 'cross-hatch' | 'zigzag';
  strokeWidth?: number;
  strokeStyle?: 'solid' | 'dashed' | 'dotted';
  roundness?: { type: number; value?: number };
  roughness?: number;
  opacity?: number;
  points?: [number, number][];
  label?: {
    text: string;
    fontSize?: number;
    textAlign?: 'left' | 'center' | 'right';
    verticalAlign?: 'top' | 'middle' | 'bottom';
  };
  text?: string;
  fontSize?: number;
  textAlign?: 'left' | 'center' | 'right';
  verticalAlign?: 'top' | 'middle' | 'bottom';
  [key: string]: unknown;
}

export interface ConnectionAckMessage {
  type: 'connection_ack';
  sessionId: string;
  serverVersion: string;
  /** Monotonic revision of the authoritative server-side scene. */
  sceneVersion?: number;
  message: string;
  initialContext?: ContextVisualization;
  initialMessages?: ChatMessage[];
  visualElements?: ExcalidrawSkeletonElement[];
  files?: CanvasFiles;
  capabilities?: string[];
}

export interface AgentStatusMessage {
  type: 'agent_status';
  status: AgentStatus;
  stageDescription?: string;
}

export interface ContextUpdateMessage {
  type: 'context_update';
  /** Monotonic revision of the authoritative server-side scene. */
  sceneVersion?: number;
  context?: ContextVisualization | null;
  visualElements?: ExcalidrawSkeletonElement[];
  /** New or changed assets only; merge into the existing file map. */
  files?: CanvasFiles;
  changedElementIds?: string[];
  turnId?: string;
  /** True while the agent is still streaming more patches for this turn. */
  partial?: boolean;
  summary?: string;
}

export interface AgentChatMessage extends ChatMessage {
  type: 'agent_message';
  sender: 'agent';
}

export interface ErrorMessage {
  type: 'error';
  message: string;
  code?: string;
  details?: string;
}

export type ServerMessage =
  | ConnectionAckMessage
  | AgentStatusMessage
  | ContextUpdateMessage
  | AgentChatMessage
  | ErrorMessage
  | { type: 'agent_thought'; thought: string }
  | { type: 'pong' };

export type ClientMessage =
  | {
      type: 'user_message';
      content: string;
      visualElements?: unknown[];
      files?: CanvasFiles;
      selectedElementIds?: string[];
      theme?: 'light' | 'dark';
      sessionId?: string;
      clientTimestamp?: string;
    }
  | {
      /** Persist direct user edits without starting an agent turn. */
      type: 'sync_scene';
      visualElements: unknown[];
      files?: CanvasFiles;
      /** Server scene revision that this browser edit was based on. */
      baseSceneVersion?: number;
      sessionId?: string;
    }
  | {
      /** Re-index the workspace and redraw only the generated codebase map. */
      type: 'refresh_codebase_map';
      sessionId?: string;
    }
  | {
      type: 'revert_turn';
      turnId: string;
    }
  | {
      type: 'select_preset';
      presetId: string;
      sessionId?: string;
    }
  | {
      type: 'reset_session';
      sessionId?: string;
    }
  | {
      type: 'ping';
    }
  | {
      type: 'request_current_state';
      sessionId?: string;
    };

/** A subdirectory the server exposes for repository browsing. */
export interface DirectoryEntry {
  name: string;
  path: string;
}

export interface WorkspaceBrowseResponse {
  path: string;
  parent: string | null;
  entries: DirectoryEntry[];
}

/** Codebase map metadata, without the (large) element list. */
export interface WorkspaceCodebaseSummary {
  root: string;
  name: string;
  totalFiles: number;
  indexedFiles: number;
  drawnFiles: number;
  edges: number;
  languages: Record<string, number>;
  languagesLabel: string;
  truncated: boolean;
}

export interface WorkspaceStatusResponse {
  root: string | null;
  name: string | null;
  codebase: WorkspaceCodebaseSummary | null;
  execEnabled: boolean;
}

export interface BindWorkspaceResponse {
  root: string | null;
  name: string | null;
  codebase: WorkspaceCodebaseSummary | null;
  warning: string | null;
}
