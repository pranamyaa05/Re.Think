/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, expect, it, vi } from 'vitest';
import { ApiError, type ApiError as TApiError } from '@/lib/api';

// ---- API client error mapping ------------------------------------------------

describe('api error mapping', () => {
  const origFetch = globalThis.fetch;

  function fakeResponse(status: number, body?: string | null, headers?: Record<string, string>): Response {
    return new Response(body ?? '', {
      status,
      headers: { 'content-type': 'application/json', ...(headers ?? {}) },
    });
  }

  afterEach(() => {
    globalThis.fetch = origFetch;
  });

  async function expectError(promise: Promise<unknown>): Promise<TApiError> {
    let caught: unknown;
    try {
      await promise;
    } catch (e) {
      caught = e;
    }
    if (!caught || !(caught instanceof ApiError)) {
      throw new Error(`Expected ApiError, got ${caught}`);
    }
    return caught as TApiError;
  }

  it('maps a network failure to a typed ApiError with code network_error', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new Error('ECONNREFUSED')));
    const api = await import('@/lib/api');
    let caught: unknown;
    try {
      await api.api.me();
    } catch (e) {
      caught = e;
    }
    expect(caught instanceof ApiError).toBe(true);
    expect((caught as TApiError).name).toBe('ApiError');
    expect((caught as TApiError).status).toBe(0);
    expect((caught as TApiError).code).toBe('network_error');
    expect((caught as TApiError).message).toContain('Network error');
  });

  it('maps a 401 to ApiError.isUnauthorized', async () => {
    globalThis.fetch = vi.fn(() => fakeResponse(401, JSON.stringify({ detail: 'session expired' })));
    const api = await import('@/lib/api');
    let caught: unknown;
    try {
      await api.api.me();
    } catch (e) {
      caught = e;
    }
    const err = caught as TApiError;
    expect(err instanceof ApiError).toBe(true);
    expect(err.status).toBe(401);
    expect(err.isUnauthorized).toBe(true);
    expect(err.message).toBe('Your session expired. Please sign in again.');
  });

  it('maps a 429 to ApiError.isRateLimited and parses Retry-After seconds', async () => {
    globalThis.fetch = vi.fn(() =>
      fakeResponse(429, JSON.stringify({ detail: 'too many requests' }), { 'retry-after': '12' }),
    );
    const api = await import('@/lib/api');
    const err = expectError(api.api.me());
    expect(err.status).toBe(429);
    expect(err.isRateLimited).toBe(true);
    expect(err.retryAfterSeconds).toBe(12);
    expect(err.message).toContain('Retry after 12s.');
  });

  it('maps a 429 with an HTTP-date Retry-After to seconds', async () => {
    const future = new Date(Date.now() + 3_000_000).toUTCString();
    globalThis.fetch = vi.fn(() => fakeResponse(429, null, { 'retry-after': future }));
    const api = await import('@/lib/api');
    const err = expectError(api.api.me());
    expect(err.retryAfterSeconds).toBeGreaterThan(0);
    expect(err.retryAfterSeconds).toBeLessThanOrEqual(60);
  });

  it('maps a 503 to ApiError.isUnavailable with service_unavailable code', async () => {
    globalThis.fetch = vi.fn(() => fakeResponse(503, JSON.stringify({ error: 'shutting down' })));
    const api = await import('@/lib/api');
    let caught: unknown;
    try {
      await api.api.me();
    } catch (e) {
      caught = e;
    }
    const err = caught as TApiError;
    expect(err instanceof ApiError).toBe(true);
    expect(err.isUnavailable).toBe(true);
    expect(err.code).toBe('service_unavailable');
  });

  it('propagates a non-2xx unknown status with its detail', async () => {
    globalThis.fetch = vi.fn(() => fakeResponse(403, JSON.stringify({ detail: 'owned by another account' })));
    const api = await import('@/lib/api');
    const err = expectError(api.api.user(1));
    expect(err.status).toBe(403);
    expect(err.message).toBe('owned by another account');
  });

  it('reuses the same handler for every endpoint under a single fetch mock', async () => {
    globalThis.fetch = vi.fn(() => fakeResponse(401));
    const api = await import('@/lib/api');
    const endpoints: Array<() => Promise<unknown>> = [
      () => api.api.me(),
      () => api.api.user(1),
      () => api.api.analyticsSummary(1),
    ];
    for (const call of endpoints) {
      const err = expectError(call());
      expect(err.status).toBe(401);
    }
  });
});








