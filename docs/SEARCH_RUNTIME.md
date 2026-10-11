# Search runtime

## Scope

The runtime gives agents one JSON search operation. It starts one Fortress process in each container. Requests use one shared browser context and a new page for each search. The page closes after the service reads the result. A semaphore limits active browser work to 12 pages. The API accepts 128 requests at once. Other requests get HTTP 503.

The default provider is DuckDuckGo's HTML results page. [The typed provider manifest](../search_runtime/providers.py) holds its URL, result selector, and extraction code. `SEARCH_URL` replaces the URL for the local load fixture. The same parser still applies.

Fortress v3 lives in the released executable. The [public patch set](../patches/README.md) cannot recreate it. The Dockerfile downloads the ARM64 v153.0.8010.36 archive and checks SHA-256 `5213d291e6e883ece6d9509fa39be1ae0a7e188592ef87318693e705be994728`. The build stops on a mismatch.

## Files in the image

| Keep | Reason |
| --- | --- |
| `chrome`, `tilion`, resource packs, ICU data, V8 snapshots | Run the Fortress engine and render pages. |
| Bundled fonts and font configuration | Keep the font set coherent with the browser persona. |
| SwiftShader and Vulkan libraries | Provide software graphics on hosts without a GPU. |
| English locale pack | Let the browser load its default locale. |
| Python, aiohttp, Playwright | Serve HTTP and drive the existing browser over local CDP. |

The build removes other locale packs, Qt shims, the activator, and symbols that `strip --strip-unneeded` can remove. It leaves build tools in the first Docker stage. It does not download Playwright's copy of Chromium.

Removing more native files needs a behavior check. Fonts and software graphics affect fingerprint surfaces. The single `chrome` executable contains both the browser and compiled Fortress changes. This public fork cannot split that executable into a smaller v3 engine.

The final image uses Debian Bookworm. `docker images` reports 1.16 GB, down from 1.42 GB with the prior Debian base. Bookworm avoids a large Mesa dependency chain. `docker image inspect` reports 330 MB. The installed Fortress directory uses 427 MiB, including a 312 MiB `chrome` file.

## Startup and isolation

The service requires `TILION_LICENSE_KEY` or a nonempty key file at `/home/search/.tilion/license.jwt`. It reads the browser's startup output. If the browser reports v1 fallback, the service stops. Do not add the key to the image or repository.

The container runs as user 10001. Chromium uses its own sandbox with the [Playwright seccomp profile](../search_runtime/seccomp_profile.json). The CDP endpoint binds to container loopback on port 9223. The HTTP API listens on port 8080. Put that API on a private network or behind an authenticated gateway.

The service accepts queries only. It does not accept agent cookies or target URLs. Pages share provider cookies in one browser context. This saves memory, and the browser process stays warm. Do not use this API for authenticated browsing.

Fortress reported `America/New_York` for the test egress. The released browser initially exposed another US timezone to pages. The service now applies Fortress's reported egress timezone to each page before navigation. A live fixture page reported `America/New_York` after this change. This check covers timezone only. It does not prove every browser fingerprint surface matches the egress.

The API limits requests in flight to 128 and gives each request a 90-second deadline. It returns HTTP 429 after a provider throttle response and pauses new provider work for 60 seconds. It returns HTTP 503 when the queue is full. These limits keep the service from opening a new browser page for every incoming request.

## Checks run on 2026-10-11

The host was an ARM64 Mac with Docker Desktop. The container used `--memory=1g --cpus=2 --pids-limit=512 --shm-size=64m` and the seccomp profile. A mounted local key enabled Fortress v3. The test image contained the final code. The license file stayed outside the image.

| Check | Result | Sampled memory peak |
| --- | --- | --- |
| 20 public searches at once | 20/20 passed in 4.5 seconds. Active pages: 12. | 621 MiB |
| 101 public searches at once | 101/101 passed in 24.0 seconds. Active pages: 12. | 709 MiB |
| Second 101 public searches | 101/101 passed in 26.8 seconds. Active pages: 12. | 714 MiB |
| 101 fixture requests at once | 101/101 passed in 9.1 seconds. Active pages: 12. | 541 MiB |
| 129 fixture requests at once | 128 passed. One got HTTP 503 at the queue limit. | Not sampled |

The memory sampler used `docker stats` about once per second. A short peak may be higher. A trial with one context per request made Chromium disconnect near 968 MiB at 20 active requests. This runtime uses one shared context for public search.

Run the fixture with `node search_runtime/load_test.mjs --fixture` on the host. Start the container with `SEARCH_URL=http://host.docker.internal:18081/search` and a mounted v3 key. Then run `node search_runtime/load_test.mjs 101`. Start a second container without `SEARCH_URL`. Run `node search_runtime/load_test.mjs 20 --public`, then `node search_runtime/load_test.mjs 101 --public`. Use `QUERY_OFFSET=101` for another set of 101 public queries.

## Deployment limits

Two 101-query public runs passed with varied queries. Earlier runs that repeated one query pattern triggered DuckDuckGo HTTP 202 and 403 responses. Another trial returned an empty HTTP 200 page for one query. The browser and API cannot control an external provider's IP limits. A production deployment needs an approved egress plan and a measured provider service level. Container memory can change with target pages, architecture, and browser release.

We pinned and tested only the ARM64 image on Docker Desktop. Run the same tests on the cloud instance type before you set production capacity. Keep CDP private, pass the key through a secret manager, and set memory and CPU limits per replica. Horizontal replicas need separate browser processes and profiles.
