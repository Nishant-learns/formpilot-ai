"""Driver loader patch for Playwright.

On systems where the distro package installs python-playwright without the
matching node-playwright package under /usr/share/nodejs/playwright/cli.js,
this directs Playwright to use an available local driver package.
"""

from __future__ import annotations

import os
from pathlib import Path


def apply_playwright_driver_patch() -> None:
    try:
        import playwright._impl._driver as _pw_driver

        default_cli = "/usr/share/nodejs/playwright/cli.js"
        if not Path(default_cli).exists():
            candidates = [
                "/home/nishant/venv/lib/python3.13/site-packages/playwright/driver/package/cli.js",
                "/home/nishant/.local/lib/python3.13/site-packages/playwright/driver/package/cli.js",
                str(Path.home() / ".local/lib/python3.13/site-packages/playwright/driver/package/cli.js"),
            ]
            for cand in candidates:
                if Path(cand).exists():
                    _cand = cand
                    _pw_driver.compute_driver_executable = lambda: (
                        os.getenv("PLAYWRIGHT_NODEJS_PATH", "/usr/bin/node"),
                        _cand,
                    )
                    break
    except Exception:
        pass


apply_playwright_driver_patch()
