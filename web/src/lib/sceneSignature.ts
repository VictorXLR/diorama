/** Fields Excalidraw changes as it restores/renders an otherwise identical scene. */
const TRANSIENT_ELEMENT_KEYS = new Set(['index', 'seed', 'updated', 'version', 'versionNonce']);

function isSceneElement(value: Record<string, unknown>): boolean {
  return (
    typeof value.id === 'string' &&
    typeof value.type === 'string' &&
    typeof value.x === 'number' &&
    typeof value.y === 'number'
  );
}

/**
 * A deterministic representation of the durable element content.
 *
 * Excalidraw invokes `onChange` for scene, file, and app-state updates. Its
 * restore/render bookkeeping changes version-like fields, so omitting those
 * lets the whiteboard distinguish a true element edit from a server-driven
 * imperative update without relying on callback timing.
 */
export function sceneSignature(value: unknown): string {
  if (value === null) {
    return 'null';
  }
  if (value === undefined) {
    return 'undefined';
  }
  if (Array.isArray(value)) {
    return `[${value.map(sceneSignature).join(',')}]`;
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const omitTransientKeys = isSceneElement(record);
    return `{${Object.keys(record)
      .filter((key) => !(omitTransientKeys && TRANSIENT_ELEMENT_KEYS.has(key)) && record[key] !== undefined)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${sceneSignature(record[key])}`)
      .join(',')}}`;
  }
  if (typeof value === 'bigint') {
    return `bigint:${value.toString()}`;
  }
  if (typeof value === 'symbol') {
    return `symbol:${String(value)}`;
  }
  if (typeof value === 'function') {
    return 'function';
  }
  return JSON.stringify(value);
}
