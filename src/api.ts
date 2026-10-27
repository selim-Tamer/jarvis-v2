export async function requestJson(path: string, options: RequestInit = {}) {
  const response = await fetch(path, {...options, signal: options.signal ?? AbortSignal.timeout(8000)});
  let body: any;
  try { body = await response.json(); }
  catch { throw new Error(`Server returned an invalid response (HTTP ${response.status}).`); }
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (HTTP ${response.status}).`);
  return body;
}
