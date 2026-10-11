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
    /** @param {string} projectId */
    listConversations: (projectId) => unwrap(client.GET('/conversations', { params: { query: { project_id: projectId } } })),

    /** @param {string} id */
    openConversation: (id) =>
      unwrap(client.GET('/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),

    /** @param {string} id @param {string} title */
    renameConversation: (id, title) =>
      unwrap(client.PATCH('/conversations/{conversation_id}', { params: { path: { conversation_id: id } }, body: { title } })),

    /** @param {string} id */
    deleteConversation: (id) =>
      unwrap(client.DELETE('/conversations/{conversation_id}', { params: { path: { conversation_id: id } } })),

    listProjects: () => unwrap(client.GET('/projects')),

    /** @param {string} name @param {string} [instructions] */
    createProject: (name, instructions = '') => unwrap(client.POST('/projects', { body: { name, instructions } })),

    /** @param {string} id */
    getProject: (id) => unwrap(client.GET('/projects/{project_id}', { params: { path: { project_id: id } } })),

    // Leaving ignorePatterns out keeps the project's patterns; changed patterns start a catalog scan.
    /** @param {string} id @param {string} name @param {string} instructions @param {string[]} [ignorePatterns] */
    updateProject: (id, name, instructions, ignorePatterns) =>
      unwrap(
        client.PATCH('/projects/{project_id}', {
          params: { path: { project_id: id } },
          body: { name, instructions, ignore_patterns: ignorePatterns },
        }),
      ),

    // Deletes the project, its folder list, catalog and chats; files in its folders are never touched.
    /** @param {string} id */
    deleteProject: (id) => unwrap(client.DELETE('/projects/{project_id}', { params: { path: { project_id: id } } })),

    /** @param {string} id @param {string} path @param {'read' | 'act'} permission */
    addProjectFolder: (id, path, permission) =>
      unwrap(client.POST('/projects/{project_id}/folders', { params: { path: { project_id: id } }, body: { path, permission } })),

    /** @param {string} id @param {number} folderId @param {'read' | 'act'} permission */
    setProjectFolderPermission: (id, folderId, permission) =>
      unwrap(
        client.PATCH('/projects/{project_id}/folders/{folder_id}', {
          params: { path: { project_id: id, folder_id: folderId } },
          body: { permission },
        }),
      ),

    /** @param {string} id @param {number} folderId */
    removeProjectFolder: (id, folderId) =>
      unwrap(client.DELETE('/projects/{project_id}/folders/{folder_id}', { params: { path: { project_id: id, folder_id: folderId } } })),

    // Queues a catalog job; its progress arrives on the /jobs/events socket like any other job.
    /** @param {string} id */
    scanProjectFiles: (id) => unwrap(client.POST('/projects/{project_id}/catalog', { params: { path: { project_id: id } } })),

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
