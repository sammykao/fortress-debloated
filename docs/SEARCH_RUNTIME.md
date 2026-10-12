# Search runtime

## Scope

The runtime gives agents one JSON search operation. It starts one Fortress process in each container. Requests use one shared browser context and a new page for each search. The page closes after the service reads the result. A semaphore limits active browser work to 12 pages. The API accepts 128 requests at once. Other requests get HTTP 503.

The default provider is DuckDuckGo's HTML results page. [The typed provider manifest](../search_runtime/providers.py) holds its URL, result selector, and extraction code. `SEARCH_URL` replaces the URL for the local load fixture. The same parser still applies.

Fortress v3 lives in the released executable. The [public patch set](../patches/README.md) cannot recreate it. The Dockerfile downloads the v153.0.8010.36 archive for the target architecture. It checks SHA-256 `5213d291e6e883ece6d9509fa39be1ae0a7e188592ef87318693e705be994728` for ARM64 and `f677f850e64a75f4c202955649df074629306231feb4a2fa9bab0b9bbddafb6a` for AMD64. The build stops on a mismatch.

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

We tested ARM64 on Docker Desktop and AMD64 in a Cloudflare Container. Repeat load checks on each cloud instance type before you set production capacity. Keep CDP private, pass the key through a secret manager, and set memory and CPU limits per replica. Horizontal replicas need separate browser processes and profiles.

## AWS Lambda

[The Lambda image](../search_runtime/Dockerfile.lambda) reuses the search server and adds the [AWS Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter). The adapter passes Function URL or API Gateway HTTP requests to port 8081. It checks `/healthz` before it accepts a request. The browser profile and home directory use `/tmp` because [Lambda makes the image filesystem read-only](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html). The Lambda image sets `FORTRESS_NO_SANDBOX=1` for Chromium compatibility. This removes Chromium's own process sandbox inside the Lambda environment. The normal container keeps that sandbox and uses port 8080.

Build both images for the same architecture. This example uses ARM64:

```sh
docker build --platform linux/arm64 -f search_runtime/Dockerfile -t fortress-search:dev search_runtime
docker build --platform linux/arm64 --provenance=false --sbom=false -f search_runtime/Dockerfile.lambda -t fortress-search:lambda search_runtime
```

Push `fortress-search:lambda` to an Amazon ECR repository in the target AWS Region. Create an image-based Lambda function with ARM64 architecture, 1,024 MB memory, the default 512 MB of `/tmp` storage, and a 120-second timeout. Set `TILION_LICENSE_KEY` in the function environment through a secret deployment process. The server checks the key when it starts. Keep the key out of the image, repository, and shell history. Create a [Function URL with `AWS_IAM` authentication](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) or use an authenticated API Gateway. The HTTP operation remains `POST /search` with the JSON body described in the README. Direct `InvokeFunction` calls with a raw `{ "query": "..." }` payload are not supported by this HTTP image.

Use an existing ECR repository and Lambda execution role. Log in to ECR before the push. Set `FORTRESS_ECR_IMAGE_URI` to the ECR image tag. Set `FORTRESS_LAMBDA_ROLE_ARN` to the role ARN and `FORTRESS_AWS_REGION` to the target Region. Then deploy the image:

```sh
docker tag fortress-search:lambda "$FORTRESS_ECR_IMAGE_URI"
docker push "$FORTRESS_ECR_IMAGE_URI"
aws lambda create-function \
  --region "$FORTRESS_AWS_REGION" \
  --function-name fortress-search \
  --package-type Image \
  --code "ImageUri=$FORTRESS_ECR_IMAGE_URI" \
  --role "$FORTRESS_LAMBDA_ROLE_ARN" \
  --architectures arm64 \
  --memory-size 1024 \
  --timeout 120
aws lambda wait function-active-v2 \
  --region "$FORTRESS_AWS_REGION" \
  --function-name fortress-search
aws lambda create-function-url-config \
  --region "$FORTRESS_AWS_REGION" \
  --function-name fortress-search \
  --auth-type AWS_IAM
```

Configure `TILION_LICENSE_KEY` before the first invocation. Sign Function URL requests with AWS Signature Version 4. The caller needs both `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` permission. Increase `/tmp` storage only if measured profile usage requires it.

We tested the ARM64 image with the [AWS Lambda runtime interface emulator](https://github.com/aws/aws-lambda-runtime-interface-emulator) on Docker Desktop. The container used a read-only image filesystem, a 512 MB `/tmp` filesystem, a 1 GiB memory limit, and Docker's default seccomp profile. A live public search returned HTTP 200 and two results. The first invocation took 2.8 seconds. A warm invocation took 0.6 seconds. Docker reported 364 MiB at one sample after the first call. `docker image inspect` reports 332 MB for the Lambda image and 330 MB for the base image. These measurements are local. The emulator does not reproduce AWS placement, network, IAM, or scaling.

[Standard Lambda creates a separate execution environment for each concurrent request](https://docs.aws.amazon.com/lambda/latest/dg/lambda-concurrency.html). One hundred concurrent searches can start about one hundred browsers. The 12-page limit applies within each environment, but standard Lambda sends one invocation to each environment at a time. This deployment does not guarantee one outbound IP. The search provider can still throttle requests across environments.

## Cloudflare test

[The Cloudflare Worker](../search_runtime/cloudflare-worker.mjs) routes every request to one named Container. [Its config](../wrangler.fortress.jsonc) uses the `basic` instance type: 1 GiB RAM, one-quarter vCPU, and one maximum instance. Cloudflare's `default` scheduling policy is necessary because its Durable Object scheduling policy [does not accept `basic`](https://developers.cloudflare.com/containers/configuration/scheduling-policy/#choose-an-instance-size-at-runtime). The Worker checks a bearer token. It passes the Fortress key from a Worker secret when it starts the Container. The Container stops after 60 seconds without activity.

Deploy the Worker with Wrangler, then set `TILION_LICENSE_KEY` and `SEARCH_TEST_TOKEN` as Worker secrets. Keep both values out of the image and repository. The test account used Wrangler 4.135.0. Run the 30-query check with `SEARCH_API` set to the deployed Worker URL and `SEARCH_TOKEN_FILE` set to a local file containing the bearer token:

```sh
SEARCH_API=https://YOUR-WORKER.workers.dev \
SEARCH_TOKEN_FILE=/path/to/test-token \
node search_runtime/load_test.mjs 30 --public
```

The Worker also provides an authenticated `/probe-ip` route for this test. It runs `curl https://api.ipify.org` inside the Container and returns the observed IP. Thirty simultaneous probes returned HTTP 200 with one IP. A later probe burst returned no usable IP readings immediately after a search load. A retry returned 30/30 HTTP 200 with one IP. An IP echo service checks the Container's outbound path to that service. It cannot prove the address DuckDuckGo saw, and a new Container placement may change the address.

| Public search batch | Valid results | Elapsed time | Peak active pages |
| --- | ---: | ---: | ---: |
| First 30 queries | 7/30 | 27.6 seconds | 12 |
| Second 30 queries | 30/30 | 75.0 seconds | 12 |
| Third 30 queries | 30/30 | 78.2 seconds | 12 |

The first batch had 23 failures. At least one was HTTP 429 with a provider throttle error. The first test harness recorded the first failure, so it did not preserve a full status breakdown for that batch. The later batches each returned 30 HTTP 200 responses with nonempty results. Cloudflare did not expose a memory peak in these checks. Completion shows the process ran under the 1 GiB limit. Cloudflare reported the Container inactive before the second batch. A later health request took 7.0 seconds after Cloudflare again reported it inactive. These results do not establish a sustained search rate or a stable IP guarantee.
