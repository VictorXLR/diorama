import { describe, expect, it } from 'vitest';
import { sceneSignature } from '@/lib/sceneSignature';

const ELEMENT = {
  id: 'route-card',
  type: 'rectangle',
  x: 12,
  y: 24,
  width: 240,
  height: 100,
  text: 'Times Square',
  customData: { source: 'server', version: 3 },
};

describe('sceneSignature', () => {
  it('ignores Excalidraw restore bookkeeping for an otherwise identical scene', () => {
    const serverScene = [{ ...ELEMENT, index: 'a1', seed: 4, updated: 10, version: 1, versionNonce: 2 }];
    const renderedScene = [{ ...ELEMENT, index: 'b2', seed: 7, updated: 11, version: 2, versionNonce: 9 }];

    expect(sceneSignature(renderedScene)).toBe(sceneSignature(serverScene));
  });

  it('changes when the user changes durable element content', () => {
    const movedScene = [{ ...ELEMENT, x: 99 }];
    const editedScene = [{ ...ELEMENT, customData: { source: 'user', version: 3 } }];

    expect(sceneSignature(movedScene)).not.toBe(sceneSignature([ELEMENT]));
    expect(sceneSignature(editedScene)).not.toBe(sceneSignature([ELEMENT]));
  });
});
