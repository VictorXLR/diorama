import { useCallback, useEffect, useRef } from 'react';
import { CaptureUpdateAction, Excalidraw } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import type { BinaryFileData, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types';
import { Maximize2, Sparkles, Trash2 } from 'lucide-react';
import type { WhiteboardElements } from '@/lib/whiteboardGenerator';
import type { CanvasFiles } from '@/types/context';

export interface WhiteboardProps {
  elements: WhiteboardElements;
  /** Image assets referenced by `image` elements. */
  files: CanvasFiles | undefined;
  /** Element ids to briefly glow (e.g. the agent's latest changes). */
  highlightIds?: string[] | null;
  onApiReady?: (api: ExcalidrawImperativeAPI) => void;
  onClearBoard?: () => void;
  theme?: 'light' | 'dark';
  title?: string;
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
  onClearBoard,
  theme = 'light',
  title = 'Context canvas',
}: WhiteboardProps): React.JSX.Element {
  const excalidrawApiRef = useRef<ExcalidrawImperativeAPI | null>(null);
  const previousElementsRef = useRef<WhiteboardElements>([]);
  const loadedFileIdsRef = useRef<Set<string>>(new Set());
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
    api.updateScene({
      elements: elements as never,
      captureUpdate: CaptureUpdateAction.EVENTUALLY,
    });

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
  }, [elements, resolvedFiles, syncFiles]);

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
        api.updateScene({ elements: elements as never, captureUpdate: CaptureUpdateAction.NEVER });
      }
      onApiReady?.(api);
    },
    [elements, resolvedFiles, onApiReady, syncFiles],
  );

  const handleFitToScreen = useCallback((): void => {
    const api = excalidrawApiRef.current;
    const sceneElements = api?.getSceneElements();
    if (!api || !sceneElements?.length) {
      return;
    }

    try {
      api.scrollToContent(sceneElements, {
        animate: true,
        duration: 350,
        fitToViewport: true,
        viewportZoomFactor: 0.85,
      });
    } catch {
      api.scrollToContent();
    }
  }, []);

  const handleClear = useCallback((): void => {
    excalidrawApiRef.current?.resetScene();
    previousElementsRef.current = [];
    loadedFileIdsRef.current = new Set();
    onClearBoard?.();
  }, [onClearBoard]);

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
          },
        }}
        excalidrawAPI={handleExcalidrawRef}
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

      <div className="absolute top-4 left-4 z-10 flex items-center gap-2 rounded-xl border border-slate-200/80 bg-white/90 px-3.5 py-2 text-xs text-slate-700 shadow-sm backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/90 dark:text-slate-200">
        <div className="flex items-center gap-1.5 font-medium">
          <Sparkles className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
          <span className="max-w-56 truncate font-semibold text-slate-800 dark:text-slate-100">{title}</span>
        </div>
        <div className="h-3.5 w-px bg-slate-200 dark:bg-slate-700" />
        <span className="text-slate-500 dark:text-slate-400">{elements.length} elements</span>
        <div className="h-3.5 w-px bg-slate-200 dark:bg-slate-700" />
        <button
          className="flex items-center gap-1 rounded-md px-2 py-1 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          onClick={handleFitToScreen}
          title="Fit view to whiteboard content"
          type="button"
        >
          <Maximize2 className="h-3.5 w-3.5" />
          <span>Fit view</span>
        </button>
        <button
          className="flex items-center gap-1 rounded-md px-2 py-1 text-slate-500 transition-colors hover:bg-rose-50 hover:text-rose-600 dark:text-slate-400 dark:hover:bg-rose-950 dark:hover:text-rose-300"
          onClick={handleClear}
          title="Clear whiteboard"
          type="button"
        >
          <Trash2 className="h-3.5 w-3.5" />
          <span>Clear</span>
        </button>
      </div>
    </div>
  );
}

export default Whiteboard;
