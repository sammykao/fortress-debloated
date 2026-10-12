import { DurableObject } from 'cloudflare:workers';

export class FortressSearchBasic extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    if (ctx.container?.running) {
      void ctx.blockConcurrencyWhile(() => ctx.container.setInactivityTimeout(60_000));
    }
  }

  async fetch(request) {
    await this.ensureStarted();

    const url = new URL(request.url);
    url.protocol = 'http:';
    url.host = 'container';
    const forwarded = new Request(url, request);
    forwarded.headers.delete('host');
    forwarded.headers.delete('authorization');
    return this.ctx.container.getTcpPort(8080).fetch(forwarded);
  }

  async probeIp() {
    await this.ensureStarted();
    const process = await this.ctx.container.exec(['curl', '-fsS', 'https://api.ipify.org']);
    const output = await process.output();
    if (output.exitCode !== 0) throw new Error('Egress probe failed');
    return new TextDecoder().decode(output.stdout).trim();
  }

  async ensureStarted() {
    this.starting ??= this.startBrowser().finally(() => { this.starting = undefined; });
    await this.starting;
  }

  async startBrowser() {
    const container = this.ctx.container;
    if (!container.running) {
      container.start({
        enableInternet: true,
        env: { TILION_LICENSE_KEY: this.env.TILION_LICENSE_KEY },
      });
      await container.setInactivityTimeout(60_000);
    }

    const port = container.getTcpPort(8080);
    for (let attempt = 0; attempt < 240; attempt++) {
      try {
        const response = await port.fetch('http://container/healthz', {
          signal: AbortSignal.timeout(1000),
        });
        await response.body?.cancel();
        if (response.ok) return;
      } catch {}
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error('Fortress browser did not become ready');
  }
}

export default {
  fetch(request, env) {
    if (!env.SEARCH_TEST_TOKEN ||
        request.headers.get('authorization') !== `Bearer ${env.SEARCH_TEST_TOKEN}`) {
      return new Response('Unauthorized', { status: 401 });
    }
    const path = new URL(request.url).pathname;
    const container = env.FORTRESS_SEARCH.getByName('single-egress-test');
    if (path === '/probe-ip') {
      return container.probeIp().then(ip => Response.json({ ip }));
    }
    if (path !== '/search' && path !== '/healthz') {
      return new Response('Not found', { status: 404 });
    }
    return container.fetch(request);
  },
};
