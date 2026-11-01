import { describe, expect, it } from 'vitest';
import { api, ws } from '../src/lib/appdeploy-client';

describe('standalone app client surface', () => {
  it('exposes the API methods used by the dashboard', () => {
    expect(typeof api.get).toBe('function');
    expect(typeof api.post).toBe('function');
  });

  it('exposes the realtime connect function', () => {
    expect(typeof ws.connect).toBe('function');
  });
});
