import { useCallback, useEffect, useRef } from 'react';
import { CaptureUpdateAction, Excalidraw } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import type { BinaryFileData, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { DioramaWorkflows } from '@/components/DioramaWorkflows';
import type { AgentStatus, CanvasFiles } from '@/types/context';
import type { WhiteboardElements } from '@/lib/whiteboardGenerator';
import { sceneSignature } from '@/lib/sceneSignature';

export interface WhiteboardProps {
  elements: WhiteboardElements;
  /** Image assets referenced by `image` elements. */
  files: CanvasFiles | undefined;
  /** Element ids to briefly glow (e.g. the agent's latest changes). */
  highlightIds?: string[] | null;
  onApiReady?: (api: ExcalidrawImperativeAPI) => void;
  /** Receives direct user edits so they can be persisted and synced to the server. */
  onElementsChange?: (elements: WhiteboardElements) => void;
  /** Reports the ids of the currently selected elements (empty when none). */
  onSelectionChange?: (elementIds: string[]) => void;
  /** Sends a Diorama workflow prompt to the agent, straight from the canvas. */
  onRunWorkflow?: (prompt: string) => void;
  /** Re-indexes the workspace and redraws the generated codebase map. */
  onRefreshCodebaseMap?: () => void;
  agentStatus?: AgentStatus;
  isConnected?: boolean;
  /** Text of the currently selected elements, for selection-aware queries. */
  selectedLabels?: string[];
  theme?: 'light' | 'dark';
}

const CANVAS_BACKGROUND: Record<'light' | 'dark', string> = {
  light: '#f8fafc',
  dark: '#0f172a',
};

const EMPTY_FILES: CanvasFiles = {};

function toBinaryFiles(files: CanvasFiles): BinaryFileData[] {
  return Object.entries(files).map(([id, file]) => ({
    id: id as BinaryFileData['id'],
    mimeType: file.mimeType as BinaryFileData['mimeType'],
    dataURL: file.dataURL as BinaryFileData['dataURL'],
    created: file.created ?? Date.now(),
  }));
}

export function Whiteboard({
  elements,
  files,
  highlightIds,
  onApiReady,
  onElementsChange,
  onSelectionChange,
  onRunWorkflow,
  onRefreshCodebaseMap,
  agentStatus = 'idle',
  isConnected = false,
  selectedLabels = [],
  theme = 'light',
}: WhiteboardProps): React.JSX.Element {
  const excalidrawApiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const previousElementsRef = useRef<WhiteboardElements>([]);
  const loadedFileIdsRef = useRef<Set<string>>(new Set());
  const sceneSignatureRef = useRef(sceneSignature(elements));
  const lastSelectionRef = useRef<string[]>([]);
  const resolvedFiles = files ?? EMPTY_FILES;

  // Register image assets before the elements that reference them render, otherwise Excalidraw
  // shows a broken-image placeholder.
  const syncFiles = useCallback((api: ExcalidrawImperativeAPI, nextFiles: CanvasFiles): void => {
    const pending = Object.fromEntries(
      Object.entries(nextFiles).filter(([id]) => !loadedFileIdsRef.current.has(id)),
    );
    if (Object.keys(pending).length === 0) {
      return;
    }
    api.addFiles(toBinaryFiles(pending));
    for (const id of Object.keys(pending)) {
      loadedFileIdsRef.current.add(id);
    }
  }, []);

  const updateGeneratedScene = useCallback(
    (
      api: ExcalidrawImperativeAPI,
      nextElements: WhiteboardElements,
      captureUpdate: (typeof CaptureUpdateAction)[keyof typeof CaptureUpdateAction],
    ): void => {
      // Remember the durable content before the imperative update. Excalidraw
      // emits onChange later from componentDidUpdate, after this call returns.
      // A content signature remains correct across that async boundary.
      sceneSignatureRef.current = sceneSignature(nextElements);
      api.updateScene({ elements: nextElements as never, captureUpdate });
    },
    [],
  );

  useEffect(() => {
    const api = excalidrawApiRef.current;
    if (api) {
      syncFiles(api, resolvedFiles);
    }
  }, [resolvedFiles, syncFiles]);

  // Excalidraw requires imperative scene updates for generated elements.
  useEffect(() => {
    const api = excalidrawApiRef.current;
    if (!api || previousElementsRef.current === elements) {
      return;
    }

    previousElementsRef.current = elements;
    syncFiles(api, resolvedFiles);
    updateGeneratedScene(api, elements, CaptureUpdateAction.EVENTUALLY);

    if (elements.length === 0) {
      return;
    }

    const timer = setTimeout(() => {
      try {
        api.scrollToContent(elements as never, {
          fitToViewport: true,
          viewportZoomFactor: 0.85,
          animate: true,
          duration: 400,
        });
      } catch {
        api.scrollToContent();
      }
    }, 80);

    return () => clearTimeout(timer);
  }, [elements, resolvedFiles, syncFiles, updateGeneratedScene]);

  // Flash the agent's latest changes by selecting them, then release the selection so the user's
  // next click behaves normally. Selection is theme-aware and needs no element mutation.
  useEffect(() => {
    const api = excalidrawApiRef.current;
    if (!api || !highlightIds || highlightIds.length === 0) {
      return;
    }
    const present = new Set(api.getSceneElements().map((element) => element.id));
    const ids = highlightIds.filter((id) => present.has(id));
    if (ids.length === 0) {
      return;
    }
    const selectedElementIds = Object.fromEntries(ids.map((id) => [id, true as const]));
    api.updateScene({ appState: { selectedElementIds } });
    const timer = setTimeout(() => {
      api.updateScene({ appState: { selectedElementIds: {} } });
    }, 1400);
    return () => clearTimeout(timer);
  }, [highlightIds]);

  const handleExcalidrawRef = useCallback(
    (api: ExcalidrawImperativeAPI): void => {
      excalidrawApiRef.current = api;
      // Elements restored from persisted state may have arrived before the API was ready.
      syncFiles(api, resolvedFiles);
      if (previousElementsRef.current !== elements) {
        previousElementsRef.current = elements;
        updateGeneratedScene(api, elements, CaptureUpdateAction.NEVER);
      }
      onApiReady?.(api);
    },
    [elements, resolvedFiles, onApiReady, syncFiles, updateGeneratedScene],
  );

  // Keep the canvas background in step with the app theme.
  useEffect(() => {
    excalidrawApiRef.current?.updateScene({
      appState: { viewBackgroundColor: CANVAS_BACKGROUND[theme] },
    });
  }, [theme]);

  return (
    <div className="relative h-full min-w-0 flex-1 overflow-hidden bg-slate-50 dark:bg-slate-950">
      <Excalidraw
        UIOptions={{
          canvasActions: {
            loadScene: false,
            saveToActiveFile: false,
            toggleTheme: false,
            // Diorama owns these actions with its own board controls.
            clearCanvas: false,
            saveAsImage: false,
            changeViewBackgroundColor: false,
          },
        }}
        excalidrawAPI={handleExcalidrawRef}
        onChange={(nextElements, appState) => {
          const nextSignature = sceneSignature(nextElements);
          if (nextSignature !== sceneSignatureRef.current) {
            sceneSignatureRef.current = nextSignature;
            onElementsChange?.([...nextElements] as WhiteboardElements);
          }
          const selectedIds = Object.keys(appState.selectedElementIds ?? {});
          if (selectedIds.join('\u0000') !== lastSelectionRef.current.join('\u0000')) {
            lastSelectionRef.current = selectedIds;
            onSelectionChange?.(selectedIds);
          }
        }}
        initialData={{
          elements: elements as never,
          appState: {
            currentItemFontFamily: 1,
            gridSize: 20,
            viewBackgroundColor: CANVAS_BACKGROUND[theme],
          },
        }}
        theme={theme}
      />

      {onRunWorkflow && onRefreshCodebaseMap && (
        <DioramaWorkflows
          agentStatus={agentStatus}
          isConnected={isConnected}
          onRefreshCodebaseMap={onRefreshCodebaseMap}
          onRunWorkflow={onRunWorkflow}
          selectedLabels={selectedLabels}
        />
      )}
    </div>
  );
}

export default Whiteboard;
