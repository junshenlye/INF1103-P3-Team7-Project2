export async function request(path, { method = 'GET', body, signal, headers = {} } = {}) {
  const options = { method, signal, headers: { ...headers } };
  if (body instanceof FormData) options.body = body;
  else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch (cause) {
    if (cause.name === 'AbortError') throw cause;
    const error = new Error('Connection lost. Check submission status before sending again.');
    error.uncertain = true;
    throw error;
  }
  let data;
  try { data = await response.json(); }
  catch {
    const error = new Error('The response could not be read. Check submission status.');
    error.uncertain = true;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(data.issues?.map(issue => issue.message).join(' ') || `Request failed (${response.status}).`);
    error.issues = data.issues || [];
    error.status = response.status;
    error.uncertain = response.status >= 500;
    throw error;
  }
  return data;
}

export function submitBucket(projectId, modules, fileParts, key) {
  const body = new FormData();
  body.append('modules', JSON.stringify(modules));
  for (const [field, file] of fileParts) body.append(field, file);
  return request(`/api/projects/${projectId}/process`, {
    method: 'POST', body, headers: { 'Idempotency-Key': key },
  });
}
