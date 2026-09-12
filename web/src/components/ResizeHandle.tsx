import { useCallback, useEffect, useRef, useState } from 'react';
import { GripVertical } from 'lucide-react';

interface ResizeHandleProps {
  /** Current width of the panel to the right of the handle. */
  width: number;
  minWidth: number;
  maxWidth: number;
  onResize: (width: number) => void;
}

const KEYBOARD_STEP = 24;

export function ResizeHandle({ width, minWidth, maxWidth, onResize }: ResizeHandleProps): React.JSX.Element {
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; width: number } | null>(null);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>): void => {
      event.preventDefault();
      dragStartRef.current = { x: event.clientX, width };
      setIsDragging(true);
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [width],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLButtonElement>): void => {
      const start = dragStartRef.current;
      if (!start) {
        return;
      }
      // Panel sits on the right, so dragging left grows it.
      onResize(start.width + (start.x - event.clientX));
    },
    [onResize],
  );

  const endDrag = useCallback((): void => {
    dragStartRef.current = null;
    setIsDragging(false);
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>): void => {
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        onResize(width + KEYBOARD_STEP);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        onResize(width - KEYBOARD_STEP);
      }
    },
    [onResize, width],
  );

  // Excalidraw's canvas would otherwise swallow pointer events and the cursor would flicker.
  useEffect(() => {
    if (!isDragging) {
      return;
    }
    const previousCursor = document.body.style.cursor;
    const previousSelect = document.body.style.userSelect;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousSelect;
    };
  }, [isDragging]);

  return (
    <button
      aria-label="Resize chat panel. Use left and right arrow keys to adjust."
      title={`Chat width: ${width}px (${minWidth}–${maxWidth}px)`}
      className={`group relative z-20 flex w-2 shrink-0 cursor-col-resize touch-none items-center justify-center border-x border-slate-200 bg-slate-100 p-0 transition-colors hover:bg-indigo-100 focus:outline-none focus-visible:bg-indigo-100 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-indigo-950 ${isDragging ? 'bg-indigo-200 dark:bg-indigo-900' : ''}`}
      onKeyDown={handleKeyDown}
      onPointerCancel={endDrag}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      type="button"
    >
      <GripVertical className="pointer-events-none h-4 w-4 text-slate-400 group-hover:text-indigo-500 dark:text-slate-500" />
    </button>
  );
}

export default ResizeHandle;
