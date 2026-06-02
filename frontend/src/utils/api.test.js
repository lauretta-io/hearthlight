import { parseApiJson } from './api';

const buildResponse = (body, status, ok = status >= 200 && status < 300) => ({
  ok,
  status,
  text: async () => body,
});

describe('parseApiJson', () => {
  it('parses successful JSON responses', async () => {
    const response = buildResponse(JSON.stringify({ ok: true }), 200);
    await expect(parseApiJson(response, 'failed')).resolves.toEqual({ ok: true });
  });

  it('throws a readable error for plain-text 500 responses', async () => {
    const response = buildResponse('Internal Server Error', 500, false);
    await expect(parseApiJson(response, 'Failed to load')).rejects.toThrow(
      /Failed to load/i,
    );
  });

  it('throws when a 200 response is not JSON', async () => {
    const response = buildResponse('Internal Server Error', 200);
    await expect(parseApiJson(response, 'Failed to load')).rejects.toThrow(
      /non-JSON/i,
    );
  });

  it('supports fetch mocks that only implement json()', async () => {
    const response = {
      ok: true,
      status: 200,
      json: async () => ({ default_bindings: { detector: 'builtin_yolox_s_cpu' } }),
    };
    await expect(parseApiJson(response, 'failed')).resolves.toEqual({
      default_bindings: { detector: 'builtin_yolox_s_cpu' },
    });
  });
});
