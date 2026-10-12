# Fortress Debloated

This fork runs a search API on the released Fortress browser. It uses one browser process and at most 12 active search pages per container. The API accepts up to 128 requests at once. Requests within that limit wait for a browser slot. Agents receive titles, direct URLs, and snippets.

The image uses the official Fortress v153.0.8010.36 Linux ARM64 or AMD64 release for the target platform. It verifies the archive hash during the build. It removes unused locale packs, Qt shims, the activator, and build tools from the runtime image. It keeps the native browser, launcher, fonts, and SwiftShader files that the browser needs.

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

## Cloudflare test

On 2026-10-11, a Cloudflare Worker routed requests to one `basic` Container with 1 GiB RAM and one-quarter vCPU. The first 30 simultaneous public searches returned 7 valid results and 23 failures in 27.6 seconds. At least one failure was HTTP 429 after DuckDuckGo throttled. Two later batches of 30 varied searches returned 30/30 valid results in 75.0 and 78.2 seconds. The browser reached 12 active pages. These runs show that the result depends on provider behavior and that one-quarter vCPU adds substantial latency.

Thirty simultaneous IP checks from that Container reported one public IP. The checks used an IP echo service. They cannot prove which IP DuckDuckGo saw for every connection. Cloudflare may assign a different outbound IP when the Container restarts. The Container stops after 60 seconds of inactivity, so it has no idle browser process. The next request starts Fortress again. One health request took 7.0 seconds after Cloudflare reported the Container inactive. See [the test method and limits](docs/SEARCH_RUNTIME.md#cloudflare-test).

On 2026-10-12, the same Worker returned 20/20 public searches in 65.3 seconds and 30/30 in 88.1 seconds. A burst of 100 returned 24 valid results and 76 HTTP 504 deadlines in 97.9 seconds. The browser reached 12 active pages. Five searches after that burst passed, and a later batch of 30 passed. No API HTTP 429 occurred in these runs. Thirty IP probes before the burst and 30 after it reported the same address. Cloudflare then reported the Container inactive. Its next request restarted it in 11.2 seconds and reported the same address. One public search after restart passed. These checks found no persistent provider block, but they cannot guarantee a fixed IP or a future provider result. See [the dated results](docs/SEARCH_RUNTIME.md#cloudflare-test-on-2026-10-12).

## AWS Lambda

Lambda can run the same Fortress search API from an ARM64 or AMD64 container image. [The Lambda Dockerfile](search_runtime/Dockerfile.lambda) adds the AWS Lambda Web Adapter to the existing image. It keeps the browser profile and home directory in Lambda's writable `/tmp` directory. It disables Chromium's own sandbox for Lambda compatibility. The image does not contain a license key.

```sh
docker build --platform linux/arm64 -f search_runtime/Dockerfile -t fortress-search:dev search_runtime
docker build --platform linux/arm64 --provenance=false --sbom=false -f search_runtime/Dockerfile.lambda -t fortress-search:lambda search_runtime
```

Push `fortress-search:lambda` to Amazon ECR. Create an ARM64 Lambda function from that image. Start with 1,024 MB memory, the default 512 MB of `/tmp` storage, and a 120-second timeout. Supply `TILION_LICENSE_KEY` through Lambda environment configuration without putting it in the image or repository. Expose `POST /search` through a Function URL with `AWS_IAM` authentication or an authenticated API Gateway. See [the deployment steps and test limits](docs/SEARCH_RUNTIME.md#aws-lambda).

A local AWS Lambda runtime emulator returned a public search result from this image under a 1 GiB memory limit and read-only image filesystem. The first invocation took 2.8 seconds. A warm invocation took 0.6 seconds. The emulator does not measure AWS production cold starts or Lambda scaling. Standard Lambda allocates one execution environment for each concurrent invocation. One hundred concurrent requests can therefore start about one hundred browser environments and use different outbound IPs.

## Build and run

Build for your platform:

```sh
docker build --platform linux/arm64 -f search_runtime/Dockerfile -t fortress-search:dev search_runtime
```

Use `--platform linux/amd64` for Cloudflare Containers.

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
