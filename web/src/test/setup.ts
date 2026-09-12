// Setup jsdom polyfills/mocks for Excalidraw
if (typeof window === 'undefined') {
  const { JSDOM } = await import('jsdom');
  const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'http://localhost',
    pretendToBeVisual: true,
  });
  for (const key of Object.getOwnPropertyNames(dom.window)) {
    if (!(key in globalThis)) {
      try {
        (globalThis as Record<string, unknown>)[key] = (dom.window as unknown as Record<string, unknown>)[key];
      } catch {
        // Ignore uncopyable properties
      }
    }
  }
  globalThis.window = dom.window as unknown as Window & typeof globalThis;
  globalThis.document = dom.window.document;
  globalThis.navigator = dom.window.navigator;
  globalThis.devicePixelRatio = 1;
  globalThis.HTMLCanvasElement = dom.window.HTMLCanvasElement;
}

if (typeof window !== 'undefined') {
  if (typeof window.FontFace === 'undefined') {
    class MockFontFace {
      load() {
        return Promise.resolve(this);
      }
    }
    // @ts-expect-error Mock FontFace
    window.FontFace = MockFontFace;
    // @ts-expect-error Mock FontFace
    globalThis.FontFace = MockFontFace;
  }

  if (!HTMLCanvasElement.prototype.getContext) {
    // @ts-expect-error Mocking getContext for jsdom
    HTMLCanvasElement.prototype.getContext = () => ({
      filter: '',
    });
  } else {
    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    // @ts-expect-error Mocking getContext for jsdom
    HTMLCanvasElement.prototype.getContext = function (type: string, ...args: unknown[]) {
      if (type === '2d') {
        return {
          filter: '',
          fillRect: () => {},
          clearRect: () => {},
          getImageData: () => ({ data: [] }),
          putImageData: () => {},
          createImageData: () => [],
          setTransform: () => {},
          drawImage: () => {},
          save: () => {},
          fillText: () => {},
          restore: () => {},
          beginPath: () => {},
          moveTo: () => {},
          lineTo: () => {},
          closePath: () => {},
          stroke: () => {},
          translate: () => {},
          scale: () => {},
          rotate: () => {},
          arc: () => {},
          fill: () => {},
          measureText: () => ({ width: 0 }),
          transform: () => {},
          rect: () => {},
          clip: () => {},
        };
      }
      return originalGetContext.apply(this, [type, ...args] as [string]);
    };
  }
}
