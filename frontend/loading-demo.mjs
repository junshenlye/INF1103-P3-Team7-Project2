// Isolated loading-state preview. Uses fixture API responses and never calls the backend.
import http from 'node:http';
import { readFile } from 'node:fs/promises';

const root = new URL('./', import.meta.url);
const scenarios = new Set([
  'queued', 'parsing', 'extracting', 'validating',
  'success', 'failed', 'interrupted', 'offline',
]);
const started = new Map();
const limits = {
  module_count: 20,
  documents_per_module: 10,
  document_bytes: 10 * 1024 * 1024,
  request_bytes: 50 * 1024 * 1024,
  project_name_length: 150,
  module_title_length: 200,
  credit: 100,
  week_count: 52,
  media_types: ['application/pdf', 'image/png', 'image/jpeg'],
};

function snapshot(id) {
  const scenario = scenarios.has(id) ? id : 'extracting';
  const elapsed = Date.now() - (started.get(id) || Date.now());
  const stage = scenario === 'success'
    ? ['queued', 'parsing', 'extracting', 'validating', 'complete'][Math.min(4, Math.floor(elapsed / 4000))]
    : scenario;
  const status = stage === 'complete' ? 'Ready'
    : stage === 'failed' ? 'Failed'
      : stage === 'interrupted' ? 'Interrupted' : 'Processing';
  const states = stage === 'parsing' ? ['parsing', 'waiting']
    : stage === 'extracting' ? ['extracted', 'extracting']
      : ['validating', 'complete'].includes(stage) ? ['extracted', 'extracted']
        : stage === 'failed' ? ['failed', 'not_processed']
          : stage === 'interrupted' ? ['interrupted', 'not_processed']
            : ['waiting', 'waiting'];
  const documents = states.map((state, index) => ({
    document_id: `doc-${index}`,
    module_id: `module-${index}`,
    module_title: ['INF1103', 'INF1104'][index],
    filename: ['Project brief.pdf', 'Assessment guide.pdf'][index],
    state,
  }));
  const issues = status === 'Failed'
    ? [{ module_id: 'module-0', document_id: 'doc-0', message: 'The document could not be read. Try a clearer PDF or screenshot.' }]
    : status === 'Interrupted'
      ? [{ message: 'Processing stopped before a schedule could be published.' }]
      : [];
  return {
    project: {
      id, name: 'Trimester 1', week_count: 14, status, job_id: id,
      modules: [], schedule: status === 'Ready' ? { weeks: [], unscheduled: [] } : null, issues,
    },
    job: {
      id, project_id: id,
      status: status === 'Processing' ? (stage === 'queued' ? 'queued' : 'running') : status,
      stage, issues,
      progress: {
        documents, total_documents: documents.length,
        extracted_documents: states.filter(state => state === 'extracted').length,
      },
    },
  };
}

const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  const json = (status, body) => {
    response.writeHead(status, {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    response.end(JSON.stringify(body));
  };

  if (request.method !== 'GET') {
    return json(405, { issues: [{ message: 'This is a preview. Uploads are disabled.' }] });
  }
  if (url.pathname === '/api/limits') return json(200, limits);
  if (url.pathname === '/api/projects') return json(200, []);

  if (url.pathname.startsWith('/api/')) {
    const parts = url.pathname.split('/').filter(Boolean);
    const [resource, collection, id] = parts;
    if (resource !== 'api' || !['projects', 'jobs'].includes(collection) || !id || !scenarios.has(id)) {
      return json(404, { issues: [{ message: 'Unknown demo route.' }] });
    }
    if (!started.has(id)) started.set(id, Date.now());
    if (collection === 'jobs' && id === 'offline') {
      return json(503, { issues: [{ message: 'Demo: status connection is unavailable. Your saved submission is safe.' }] });
    }
    const result = snapshot(id);
    return json(200, collection === 'jobs' ? result.job : result.project);
  }

  const file = url.pathname === '/' ? 'templates/index.html'
    : url.pathname.startsWith('/static/') ? url.pathname.slice(1) : null;
  if (!file || file.split('/').includes('..')) {
    response.writeHead(404).end();
    return;
  }
  try {
    const data = await readFile(new URL(file, root));
    if (file.endsWith('.html')) {
      const scenario = url.searchParams.get('project');
      if (!scenarios.has(scenario)) {
        response.writeHead(302, { Location: '/?project=extracting' }).end();
        return;
      }
      started.set(scenario, Date.now());
    }
    response.writeHead(200, {
      'Content-Type': file.endsWith('.js') ? 'text/javascript; charset=utf-8'
        : file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    response.end(data);
  } catch {
    response.writeHead(404).end();
  }
});

server.listen(Number(process.env.PORT || 5175), '127.0.0.1', () => {
  console.log(`Loading-state preview: http://127.0.0.1:${server.address().port}/?project=queued`);
  console.log(`Scenarios: ${[...scenarios].join(', ')}`);
});
