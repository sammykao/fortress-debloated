"""A small, bounded search API backed by one Fortress browser."""

import asyncio
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import ClientSession, web
from playwright.async_api import Error as PlaywrightError, async_playwright

from providers import DUCKDUCKGO


PORT = 9223
LIMIT = 12
MAX_INFLIGHT = 128
TIMEOUT_MS = 45000
SEARCH_URL = os.environ.get("SEARCH_URL", DUCKDUCKGO.url)


async def start(app):
    app["timezone"] = None
    license_file = Path.home() / ".tilion" / "license.jwt"
    if not (os.environ.get("TILION_LICENSE_KEY") or
            (license_file.is_file() and license_file.stat().st_size)):
        raise RuntimeError("Fortress v3 needs TILION_LICENSE_KEY or a mounted license.jwt")
    engine = await asyncio.create_subprocess_exec(
        "/opt/fortress/tilion",
        "--headless=new",
        "--disable-dev-shm-usage",
        f"--remote-debugging-port={PORT}",
        "--user-data-dir=/tmp/fortress-profile",
        stderr=asyncio.subprocess.PIPE,
    )
    v1_fallback = False

    async def forward_stderr():
        nonlocal v1_fallback
        async for line in engine.stderr:
            message = line.decode(errors="replace")
            v1_fallback |= "running in v1" in message
            if "geo-matched persona to egress" in message and "tz=" in message:
                app["timezone"] = message.split("tz=", 1)[1].split()[0]
            sys.stderr.write(message)

    stderr_task = asyncio.create_task(forward_stderr())
    playwright = None
    browser = None
    try:
        async with ClientSession() as session:
            for _ in range(60):
                if engine.returncode is not None:
                    raise RuntimeError("Fortress exited before CDP was ready")
                try:
                    async with session.get(f"http://127.0.0.1:{PORT}/json/version") as response:
                        version = await response.json()
                        if "153.0.8010.36" not in version["Browser"]:
                            raise RuntimeError(f"Unexpected browser version: {version['Browser']}")
                        break
                except (OSError, asyncio.TimeoutError):
                    await asyncio.sleep(0.5)
            else:
                raise RuntimeError("Fortress CDP did not start")
        await asyncio.sleep(0)
        if v1_fallback:
            raise RuntimeError("Fortress rejected the v3 license")
        if not app["timezone"]:
            raise RuntimeError("Fortress did not report an egress timezone")
        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
        app["browser"] = browser
        app["context"] = browser.contexts[0]
        app["slots"] = asyncio.Semaphore(LIMIT)
        app["stats"] = {"active": 0, "peak": 0, "inflight": 0}
        app["retry_after"] = 0.0
        yield
    finally:
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()
        if engine.returncode is None:
            engine.terminate()
        await engine.wait()
        await stderr_task


def provider_throttled():
    return web.json_response({"error": "Search provider throttled requests"},
                             status=429, headers={"Retry-After": "60"})


async def search(request):
    try:
        body = await request.json()
        query = body["query"]
        count = body.get("count", 10)
        if not isinstance(query, str) or not 1 <= len(query) <= 500:
            raise ValueError("query must contain 1 to 500 characters")
        if type(count) is not int or not 1 <= count <= 10:
            raise ValueError("count must be an integer from 1 to 10")
    except (ValueError, KeyError, TypeError) as error:
        return web.json_response({"error": str(error)}, status=400)

    app = request.app
    if time.monotonic() < app["retry_after"]:
        return provider_throttled()
    stats = app["stats"]
    if stats["inflight"] >= MAX_INFLIGHT:
        return web.json_response({"error": "Search queue is full"}, status=503)
    stats["inflight"] += 1
    try:
        async with asyncio.timeout(90), app["slots"]:
            stats["active"] += 1
            stats["peak"] = max(stats["peak"], stats["active"])
            try:
                if time.monotonic() < app["retry_after"]:
                    return provider_throttled()
                for attempt in range(3):
                    page = await app["context"].new_page()
                    try:
                        if app["timezone"]:
                            cdp = await app["context"].new_cdp_session(page)
                            await cdp.send("Emulation.setTimezoneOverride",
                                           {"timezoneId": app["timezone"]})
                        response = await page.goto(
                            f"{SEARCH_URL}?{urlencode({'q': query})}",
                            wait_until="domcontentloaded",
                            timeout=TIMEOUT_MS,
                        )
                        if response and response.status in DUCKDUCKGO.throttle_statuses:
                            app["retry_after"] = time.monotonic() + 60
                            return provider_throttled()
                        results = await page.locator(DUCKDUCKGO.result_selector).evaluate_all(
                            DUCKDUCKGO.extract_script
                        )
                        if results:
                            return web.json_response({"query": query, "count": min(count, len(results)),
                                                      "results": results[:count]})
                        app.logger.warning("provider returned no results (HTTP %s)",
                                           response.status if response else "unknown")
                    finally:
                        try:
                            await asyncio.wait_for(page.close(), 5)
                        except (PlaywrightError, TimeoutError):
                            pass
                    if attempt < 2:
                        await asyncio.sleep(3 * (attempt + 1))
                return web.json_response({"error": "Search provider returned no results"}, status=502)
            except Exception as error:
                app.logger.exception("search failed")
                return web.json_response({"error": type(error).__name__}, status=502)
            finally:
                stats["active"] -= 1
    except TimeoutError:
        return web.json_response({"error": "Search deadline exceeded"}, status=504)
    finally:
        stats["inflight"] -= 1


async def health(request):
    app = request.app
    ready = app["browser"].is_connected()
    return web.json_response({"ready": ready, **app["stats"]},
                             status=200 if ready else 503)


app = web.Application(client_max_size=4096)
app.cleanup_ctx.append(start)
app.router.add_post("/search", search)
app.router.add_get("/healthz", health)
web.run_app(app, host="0.0.0.0", port=8080)
