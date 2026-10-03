// @ts-check
// Typed client for the local backend, used by the Electron main process. The routes and their
// parameters come from schema.d.ts, generated from the backend's OpenAPI description
// (openapi.json), so `npm run typecheck` fails if a call here no longer matches the backend.

const createClient = require('openapi-fetch').default;

/** @typedef {import('./schema').paths} paths */

/**
 * @param {string} baseUrl
 * @param {() => string | null} getToken
 */
function createApiClient(baseUrl, getToken) {
  /** @type {import('openapi-fetch').Client<paths>} */
  const client = createClient({ baseUrl });

  client.use({
    onRequest({ request }) {
      const token = getToken();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },
  });

  // Returns the reply body, or throws with the backend's `detail` message instead of only the status.
  /**
   * @template T
   * @param {Promise<{ data?: T, error?: unknown, response: Response }>} call
   * @returns {Promise<T>}
   */
  async function unwrap(call) {
    const { data, error, response } = await call;
    if (!response.ok) {
      const detail = /** @type {{ detail?: unknown }} */ (error ?? {}).detail;
      throw new Error(typeof detail === 'string' ? detail : `${response.url} failed: ${response.status}`);
    }
    return /** @type {T} */ (data);
  }

  return {
    listConversations: () => unwrap(client.GET('/conversations')),

    /** @param {string} id */
    openConversation: (id) =>
      unwrap(client.GET('/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),

    /** @param {string} id @param {string} title */
    renameConversation: (id, title) =>
      unwrap(client.PATCH('/conversations/{conversation_id}', { params: { path: { conversation_id: id } }, body: { title } })),

    /** @param {string} id */
    deleteConversation: (id) =>
      unwrap(client.DELETE('/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),
  };
}

module.exports = { createApiClient };
