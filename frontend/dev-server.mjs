// Frontend-only preview. API requests stream unchanged to the existing service.
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('.', import.meta.url));
const upstream = new URL(process.env.BACKEND_URL || 'http://127.0.0.1:5173');
if (upstream.protocol !== 'http:') throw new Error('Use a local HTTP backend for this development preview.');
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8' };
const server = http.createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    const proxy = http.request(new URL(request.url, upstream), {
      method: request.method,
      headers: { ...request.headers, host: upstream.host },
    }, incoming => {
      response.writeHead(incoming.statusCode, incoming.headers);
      incoming.pipe(response);
    });
    proxy.on('error', () => {
      if (response.headersSent) { response.destroy(); return; }
      response.writeHead(502, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ issues: [{ code: 'preview_backend_unavailable', message: 'The local backend could not be reached.', scope: 'request', severity: 'error' }] }));
    });
    request.on('aborted', () => proxy.destroy());
    request.pipe(proxy);
    return;
  }
  const file = url.pathname === '/' ? 'templates/index.html' : url.pathname === '/documents' ? 'templates/documents.html' : url.pathname.startsWith('/static/') ? url.pathname.slice(1) : null;
  if (!file || file.split('/').includes('..')) { response.writeHead(404); response.end(); return; }
  try {
    const data = await readFile(path.join(root, file));
    response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    response.end(data);
  } catch { response.writeHead(404); response.end(); }
});
server.listen(Number(process.env.PORT || 5174), '127.0.0.1', () => console.log(`Stackplan frontend: http://127.0.0.1:${server.address().port}`));
