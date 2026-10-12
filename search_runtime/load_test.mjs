import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';

const fixture = process.argv.includes('--fixture');

if (fixture) {
  createServer((request, response) => {
    const query = new URL(request.url, 'http://localhost').searchParams.get('q') || '';
    const url = `https://example.test/?q=${encodeURIComponent(query)}`;
    const snippet = query === 'timezone-smoke'
      ? '<span class="result__snippet" id="timezone"></span><script>document.getElementById("timezone").textContent=Intl.DateTimeFormat().resolvedOptions().timeZone</script>'
      : '<span class="result__snippet">Fixture</span>';
    response.setHeader('content-type', 'text/html');
    setTimeout(() => response.end(`<div class="result"><a class="result__a" href="${url}">Result</a>${snippet}</div>`), 250);
  }).listen(18081, '0.0.0.0', () => console.log('fixture on :18081'));
} else {
  const count = Number(process.argv[2] || 20);
  const publicRun = process.argv.includes('--public');
  const offset = Number(process.env.QUERY_OFFSET || 0);
  const api = process.env.SEARCH_API || 'http://127.0.0.1:18080';
  const headers = { 'content-type': 'application/json' };
  const token = process.env.SEARCH_TOKEN_FILE &&
    readFileSync(process.env.SEARCH_TOKEN_FILE, 'utf8').trim();
  if (token) headers.authorization = `Bearer ${token}`;
  let peak = 0;
  const sample = setInterval(async () => {
    try {
      const health = await (await fetch(`${api}/healthz`, { headers })).json();
      peak = Math.max(peak, health.active);
    } catch {}
  }, 100);
  const started = Date.now();
  const subjects = ['solar energy', 'ocean currents', 'rainforest ecology', 'bread baking',
    'robotics education', 'urban planning', 'classical music', 'earthquakes',
    'computer security', 'renewable materials', 'space telescopes'];
  const intents = ['overview', 'history', 'research', 'examples', 'projects',
    'guide', 'tutorial', 'books', 'facts', 'timeline', 'statistics', 'science',
    'methods', 'comparison', 'case studies', 'training', 'resources', 'design',
    'analysis', 'applications', 'policy', 'datasets', 'maps', 'interviews',
    'workshops', 'courses', 'standards', 'community', 'journal', 'glossary'];
  const responses = await Promise.all(Array.from({ length: count }, async (_, i) => {
    const index = i + offset;
    const query = publicRun
      ? `${subjects[index % subjects.length]} ${intents[Math.floor(index / subjects.length) % intents.length]}`
      : `fortress load ${i}`;
    try {
      const response = await fetch(`${api}/search`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ query, count: 1 }),
        signal: AbortSignal.timeout(150000),
      });
      const body = await response.json();
      return { status: response.status, query, body };
    } catch (error) {
      return { status: 0, query, body: { error: error.message } };
    }
  })).finally(() => clearInterval(sample));
  const failures = responses.filter(({ status, query, body }) =>
    status !== 200 || body.query !== query || body.count !== 1 ||
    (publicRun ? !body.results?.[0]?.title ||
      !body.results[0].url?.startsWith('http') || body.results[0].rank !== 1 :
      body.results?.[0]?.url !== `https://example.test/?q=${encodeURIComponent(query)}`));
  const statuses = {};
  for (const { status } of responses) statuses[status] = (statuses[status] || 0) + 1;
  console.log(JSON.stringify({ requests: count, failures: failures.length, statuses,
    peakActive: peak, elapsedMs: Date.now() - started, sample: failures[0] }));
  if (failures.length) process.exitCode = 1;
}
