import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from './client'
import { AUTH_TOKEN_KEYS, REFRESH_TOKEN_KEYS, storeAuthTokens } from '../lib/auth'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API authentication transport', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('attaches the stored access token to business requests', async () => {
    storeAuthTokens('access-token', 'refresh-token')
    const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(jsonResponse({ ok: true }))

    await expect(api.get('/protected')).resolves.toEqual({ ok: true })

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer access-token')
  })

  it('clears the browser session when a 401 cannot be refreshed', async () => {
    storeAuthTokens('expired-access', 'expired-refresh')
    const expiredListener = vi.fn()
    window.addEventListener('mingjian:auth-expired', expiredListener)
    vi.spyOn(window, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid or expired token' }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: 'Invalid or expired refresh token' }, 401))

    await expect(api.get('/protected')).rejects.toMatchObject({ status: 401 })

    for (const key of [...AUTH_TOKEN_KEYS, ...REFRESH_TOKEN_KEYS]) {
      expect(window.localStorage.getItem(key)).toBeNull()
    }
    expect(expiredListener).toHaveBeenCalledTimes(1)
    window.removeEventListener('mingjian:auth-expired', expiredListener)
  })
})

describe('API no-content transport', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('resolves void on a 204 with no body, without parsing JSON', async () => {
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValue(new Response(null, { status: 204 }))

    await expect(api.deleteNoContent('/variable-templates/t1')).resolves.toBeUndefined()

    const call = fetchMock.mock.calls.at(-1)
    expect(String(call?.[0])).toBe('/api/variable-templates/t1')
    expect(call?.[1]?.method).toBe('DELETE')
  })

  it('propagates API errors with their status instead of resolving', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValue(
      jsonResponse({ detail: 'Variable template t1 was not found.' }, 404),
    )

    await expect(api.deleteNoContent('/variable-templates/t1')).rejects.toMatchObject({
      status: 404,
    })
  })
})
