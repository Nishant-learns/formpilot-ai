import asyncio
import time
from typing import Dict, Any, Optional
from playwright.async_api import Page, Error as PlaywrightError

class ResilientNavigator:
    """Non-blocking resilient navigation engine with adaptive hydration & context recovery."""

    @classmethod
    async def navigate_safely(
        cls,
        page: Page,
        url: str,
        timeout_ms: int = 45000,
        max_hydration_wait_ms: int = 15000
    ) -> Dict[str, Any]:
        """
        Navigates using non-blocking commit, awaits DOMContentLoaded,
        and uses an adaptive hydration observation loop to catch client redirection context destructions.
        """
        start_time = time.time()
        
        # Step 1: Non-blocking commit
        try:
            target_url = url
            if "jeemain.nta.nic.in" in url or "exams.nta.ac.in" in url:
                try:
                    import urllib.request, re
                    req = urllib.request.Request(
                        url if "http" in url else f"https://{url}",
                        headers={
                            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                        matches = re.findall(r'https://examinationservices\.nic\.in/[^"\'<>\s]*Home\.aspx[^"\'<>\s]*', html, re.I)
                        if matches:
                            unique = list(dict.fromkeys(matches))
                            sorted_matches = sorted(
                                unique,
                                key=lambda x: re.findall(r'\d{4}', x)[-1] if re.findall(r'\d{4}', x) else '0',
                                reverse=True,
                            )
                            target_url = sorted_matches[0].replace("&amp;", "&")
                        else:
                            m = re.search(r'href=["\'](https://examinationservices\.nic\.in/[^"\']*)["\']', html)
                            if m:
                                target_url = m.group(1).replace("&amp;", "&")
                except Exception:
                    pass

            response = await page.goto(target_url, wait_until="commit", timeout=timeout_ms)
            status_code = response.status if response else 200

            if status_code == 403 and "examinationservices.nic.in" not in target_url:
                try:
                    import urllib.request, re
                    req = urllib.request.Request(
                        target_url,
                        headers={
                            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        html = resp.read().decode("utf-8", errors="ignore")
                        matches = re.findall(r'https://examinationservices\.nic\.in/[^"\'<>\s]*Home\.aspx[^"\'<>\s]*', html, re.I)
                        if matches:
                            unique = list(dict.fromkeys(matches))
                            sorted_matches = sorted(
                                unique,
                                key=lambda x: re.findall(r'\d{4}', x)[-1] if re.findall(r'\d{4}', x) else '0',
                                reverse=True,
                            )
                            live_app_url = sorted_matches[0].replace("&amp;", "&")
                        else:
                            m = re.search(r'href=["\'](https://examinationservices\.nic\.in/[^"\']*)["\']', html)
                            live_app_url = m.group(1).replace("&amp;", "&") if m else None
                        if live_app_url:
                            response = await page.goto(live_app_url, wait_until="commit", timeout=timeout_ms)
                            status_code = response.status if response else 200
                except Exception:
                    pass
        except PlaywrightError as pe:
            # Handle client-side immediate redirect
            if "net::ERR_ABORTED" in str(pe) or "Execution context was destroyed" in str(pe):
                # Absorb redirect and wait for target context
                await asyncio.sleep(1.0)
                status_code = 200
            else:
                raise pe

        # Step 2: Await DOM Content Loaded
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass  # Proceed to adaptive observation loop

        # Step 3: Adaptive Hydration Observation Loop
        hydrated = False
        last_elem_count = 0
        stable_cycles = 0
        loop_start = time.time()

        while (time.time() - loop_start) * 1000 < max_hydration_wait_ms:
            try:
                state_info = await page.evaluate("""
                () => {
                    // Check ASP.NET async postback
                    const isAspBusy = window.Sys && window.Sys.WebForms && window.Sys.WebForms.PageRequestManager && window.Sys.WebForms.PageRequestManager.getInstance().get_isInAsyncPostBack();
                    // Check jQuery active
                    const isJqBusy = window.jQuery && window.jQuery.active > 0;
                    // Count interactive inputs
                    const inputs = document.querySelectorAll('input, select, textarea, button, a').length;
                    return {
                        readyState: document.readyState,
                        isBusy: Boolean(isAspBusy || isJqBusy),
                        elemCount: inputs
                    };
                }
                """)

                # If DOM is interactive or complete and element count has stabilized
                if state_info.get("readyState") in ("interactive", "complete") and not state_info.get("isBusy"):
                    elem_count = state_info.get("elemCount", 0)
                    if elem_count > 0 and elem_count == last_elem_count:
                        stable_cycles += 1
                        if stable_cycles >= 2:  # Stabilized across consecutive observations
                            hydrated = True
                            break
                    else:
                        stable_cycles = 0
                        last_elem_count = elem_count
            except PlaywrightError as pe:
                # Execution context destroyed by client redirection (e.g., SPA route change)
                if "Execution context was destroyed" in str(pe) or "Target closed" in str(pe):
                    await asyncio.sleep(0.5)
                    continue
                else:
                    break
            except Exception:
                break

            await asyncio.sleep(0.4)

        elapsed = round(time.time() - start_time, 2)
        return {
            "success": True,
            "url": page.url,
            "status_code": status_code,
            "elapsed_seconds": elapsed,
            "hydrated": hydrated
        }

    @classmethod
    async def capture_high_res_screenshot(cls, page: Page) -> bytes:
        """Captures clear full viewport screenshot for the candidate Cockpit stream."""
        try:
            return await page.screenshot(type="jpeg", quality=85, full_page=False, timeout=3000, animations="disabled")
        except Exception as e:
            print(f"[ResilientNavigator] Screenshot error: {e}")
            return b""
