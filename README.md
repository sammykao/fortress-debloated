# Fortress Debloated

This fork runs a search API on the released Fortress browser. It uses one browser process and at most 12 active search pages per container. The API accepts up to 128 requests at once. Requests within that limit wait for a browser slot. Agents receive titles, direct URLs, and snippets.

The image uses the official Fortress v153.0.8010.36 Linux ARM64 release. It verifies the archive hash during the build. It removes unused locale packs, Qt shims, the activator, and build tools from the runtime image. It keeps the native browser, launcher, fonts, and SwiftShader files that the browser needs.

**Source limit:** The public patches in this fork are an older demonstration set. The current v3 persona generator and some engine changes exist only in the [released binary](https://github.com/tiliondev/fortress/releases/tag/v153.0.8010.36). This image repackages that binary. It does not rebuild v3 from source or replace Chromium with an HTTP client.

## Measured status

These runs used Docker Desktop on an ARM64 Mac on 2026-10-11. The container had 1 GiB RAM, two CPUs, and Chromium's sandbox enabled. A valid local key enabled Fortress v3. We sampled memory with `docker stats`.

| Check | Result |
| --- | --- |
| Runtime image | `docker images` reports 1.16 GB. `docker image inspect` reports 330 MB. |
| Fortress bundle in the image | 427 MiB installed. The stripped `chrome` file is 312 MiB. |
| 20 simultaneous public searches | 20/20 passed in 4.5 seconds. Active pages: 12. Sampled peak: 621 MiB. |
| 101 simultaneous public searches | 101/101 passed in 24.0 seconds. Active pages: 12. Sampled peak: 709 MiB. |
| Second set of 101 public searches | 101/101 passed in 26.8 seconds. Active pages: 12. Sampled peak: 714 MiB. |
| 101 simultaneous fixture requests | 101/101 passed in 9.1 seconds. Active pages: 12. Sampled peak: 541 MiB. |
| 129 simultaneous fixture requests | 128 passed. One received HTTP 503 when the queue reached its limit. |

The public runs used varied queries. Earlier runs that repeated one query pattern triggered DuckDuckGo HTTP 202 and 403 responses. Another trial returned an empty HTTP 200 page for one query. The API returns HTTP 429 and pauses new provider work for 60 seconds after a throttle response. These results show local burst capacity. They do not establish a production service level for DuckDuckGo or a cloud host.

## Build and run

Build on ARM64:

```sh
docker build --platform linux/arm64 -f search_runtime/Dockerfile -t fortress-search:dev .
```

Inject `TILION_LICENSE_KEY` from your secret manager. The browser checks this key when it starts. The API stops if the key is absent or the browser reports v1 fallback. You can also mount a nonempty key file at `/home/search/.tilion/license.jwt`. Keep the key outside the repository. Review the [Fortress license](LICENSE) and [subscription terms](SUBSCRIPTION-TERMS.md) before production use.

```sh
docker run --rm --name fortress-search \
  --init --memory=1g --cpus=2 --pids-limit=512 --shm-size=64m \
  --security-opt seccomp=search_runtime/seccomp_profile.json \
  --env TILION_LICENSE_KEY \
  -p 127.0.0.1:8080:8080 fortress-search:dev
```

Keep port 8080 on a private network or behind an authenticated gateway. The browser's CDP port stays on container loopback. The [seccomp profile](search_runtime/seccomp_profile.json) comes from [Playwright's Docker profile](https://github.com/microsoft/playwright/blob/d9f2fd3e2232ace8e317a84eda6cb86e25bcf49c/utils/docker/seccomp_profile.json). It permits Chromium to create its own sandbox inside the container.

Send a search request:

```sh
curl -fsS http://127.0.0.1:8080/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"fortress chromium github","count":3}'
```

`POST /search` accepts a query of 1 to 500 characters and a count from 1 to 10. It returns `query`, `count`, and `results`. Each result has `title`, `url`, `snippet`, and `rank`. `GET /healthz` reports browser readiness, active pages, and requests in flight. The API returns HTTP 429 for provider throttling, 503 for a full queue, and 504 after a 90-second request deadline.

The service accepts public search queries only. Browser pages share provider cookies. Do not send user credentials or authenticated browsing tasks to this API. The service applies Fortress's reported egress timezone to each page before navigation.

## Repeat the load checks

Start the local fixture in one terminal:

```sh
node search_runtime/load_test.mjs --fixture
```

Start a container in a second terminal:

```sh
docker run --rm --name fortress-search-test \
  --init --memory=1g --cpus=2 --pids-limit=512 --shm-size=64m \
  --security-opt seccomp=search_runtime/seccomp_profile.json \
  --env TILION_LICENSE_KEY \
  -e SEARCH_URL=http://host.docker.internal:18081/search \
  -p 127.0.0.1:18080:8080 fortress-search:dev
```

Then run `node search_runtime/load_test.mjs 101`. Stop that container and start one without `SEARCH_URL`. Run `node search_runtime/load_test.mjs 20 --public` and `node search_runtime/load_test.mjs 101 --public`. Use `QUERY_OFFSET=101` for a second public query set. Record `docker stats` during each run.

See [Search runtime design and limits](docs/SEARCH_RUNTIME.md) for the file inventory, deployment limits, and test method. The other files in `docs/` describe the upstream Fortress project.
