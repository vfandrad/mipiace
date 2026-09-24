import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, extractErrorMessage, fetchOrders, request, unwrapList } from './api';
import { ADMIN_API_KEY, API_BASE_URL } from './config';

function mockFetch(response: Partial<Response> & { jsonBody?: unknown; textBody?: string }) {
  const stub = vi.fn().mockResolvedValue({
    ok: response.ok ?? true,
    status: response.status ?? 200,
    json: async () => response.jsonBody,
    text: async () => response.textBody ?? JSON.stringify(response.jsonBody ?? null),
  } as Response);
  vi.stubGlobal('fetch', stub);
  return stub;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('extractErrorMessage', () => {
  it('usa o detail em string do FastAPI', () => {
    expect(extractErrorMessage({ detail: 'Produto não encontrado' }, 404)).toBe(
      'Produto não encontrado',
    );
  });

  it('junta os erros de validação do Pydantic', () => {
    const payload = {
      detail: [
        { loc: ['body', 'base_price'], msg: 'value is not a valid float' },
        { loc: ['body', 'name'], msg: 'field required' },
      ],
    };
    expect(extractErrorMessage(payload, 422)).toBe(
      'base_price: value is not a valid float; name: field required',
    );
  });

  it('cai numa mensagem útil por status quando não há detail', () => {
    expect(extractErrorMessage(null, 401)).toContain('Chave de acesso inválida');
    expect(extractErrorMessage({}, 409)).toContain('conflita');
    expect(extractErrorMessage({}, 418)).toContain('HTTP 418');
  });
});

describe('request', () => {
  it('envia a chave administrativa e a base configurada', async () => {
    const stub = mockFetch({ jsonBody: { ok: true } });
    await request('/api/products');

    const [url, init] = stub.mock.calls[0];
    expect(url).toBe(`${API_BASE_URL}/api/products`);
    expect((init.headers as Record<string, string>)['X-API-Key']).toBe(ADMIN_API_KEY);
  });

  it('monta a query string ignorando valores vazios', async () => {
    const stub = mockFetch({ jsonBody: [] });
    await fetchOrders({ status: 'novo', limit: undefined });
    expect(stub.mock.calls[0][0]).toBe(`${API_BASE_URL}/api/orders?status=novo`);
  });

  it('transforma erro do backend em ApiError com a mensagem do detail', async () => {
    mockFetch({ ok: false, status: 400, jsonBody: { detail: 'Status inválido' } });
    await expect(request('/api/orders/1/status', { method: 'PATCH' })).rejects.toMatchObject({
      name: 'ApiError',
      status: 400,
      message: 'Status inválido',
    });
  });

  it('vira ApiError de rede quando o fetch rejeita', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    const error = await request('/api/products').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    // O `as` vem depois do toBeInstanceOf acima: a asserção de tipo só é
    // honesta porque o teste já provou que é um ApiError.
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toContain('servidor');
  });

  it('devolve undefined em 204 sem tentar parsear o corpo', async () => {
    mockFetch({ status: 204, textBody: '' });
    await expect(request('/api/products/1', { method: 'DELETE' })).resolves.toBeUndefined();
  });
});

describe('unwrapList', () => {
  it('aceita lista pura e lista embrulhada', () => {
    expect(unwrapList([{ id: 1 }], 'products')).toHaveLength(1);
    expect(unwrapList({ products: [{ id: 1 }, { id: 2 }] }, 'products')).toHaveLength(2);
    expect(unwrapList({ items: [{ id: 1 }] }, 'products')).toHaveLength(1);
    expect(unwrapList(null, 'products')).toEqual([]);
  });
});
