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

    // Queued and running jobs, newest first; live changes arrive on the /jobs/events socket.
    listActiveJobs: () => unwrap(client.GET('/jobs', { params: { query: { state: ['queued', 'running'] } } })),

    // Model runtime, models, disk space and OCR, each with a fix when something is wrong.
    healthChecks: () => unwrap(client.GET('/health/checks')),

    listFolders: () => unwrap(client.GET('/folders')),

    /** @param {string} path */
    addFolder: (path) => unwrap(client.POST('/folders', { body: { path } })),

    /** @param {number} id */
    removeFolder: (id) => unwrap(client.DELETE('/folders/{folder_id}', { params: { path: { folder_id: id } } })),

    // Queues an ingest job over every indexed folder; fails with the backend's message if one is already active.
    startIndexing: () => unwrap(client.POST('/ingest')),

    /** @param {string} id */
    cancelJob: (id) => unwrap(client.POST('/jobs/{job_id}/cancel', { params: { path: { job_id: id } } })),
  };
}

module.exports = { createApiClient };
