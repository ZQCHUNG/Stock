"""R57: PDF Report Export via Playwright

Renders Vue frontend pages in headless Chromium and prints to PDF.
Supports: ReportView, BacktestView, PortfolioView.
"""

import asyncio
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Default base URL (frontend dev server or production static)
_DEFAULT_BASE_URL = "http://localhost:5173"


def _get_base_url() -> str:
    """Get the frontend base URL for rendering."""
    import os
    return os.environ.get("PDF_BASE_URL", _DEFAULT_BASE_URL)


async def render_page_to_pdf(
    route: str,
    wait_selector: str = ".n-card",
    wait_timeout: int = 30000,
    extra_wait_ms: int = 2000,
    format_: str = "A4",
    landscape: bool = False,
) -> bytes:
    """Render a Vue frontend route to PDF using Playwright.

    Args:
        route: Vue router path (e.g., "/report?code=2330")
        wait_selector: CSS selector to wait for before printing
        wait_timeout: Max time (ms) to wait for selector
        extra_wait_ms: Additional wait after selector found (for charts to render)
        format_: Paper format (A4, Letter, etc.)
        landscape: Landscape orientation

    Returns:
        PDF bytes
    """
    from playwright.async_api import async_playwright

    base_url = _get_base_url()
    url = f"{base_url}{route}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1280, "height": 900})

            # Navigate and wait for page content
            await page.goto(url, wait_until="networkidle", timeout=wait_timeout)

            # Wait for Vue components to render
            try:
                await page.wait_for_selector(wait_selector, timeout=wait_timeout)
            except Exception:
                logger.warning(f"Selector '{wait_selector}' not found, proceeding anyway")

            # Extra wait for ECharts animations to complete
            if extra_wait_ms > 0:
                await asyncio.sleep(extra_wait_ms / 1000)

            # Generate PDF
            pdf_bytes = await page.pdf(
                format=format_,
                landscape=landscape,
                print_background=True,
                margin={"top": "15mm", "bottom": "15mm", "left": "10mm", "right": "10mm"},
            )

            return pdf_bytes
        finally:
            await browser.close()


async def export_report_pdf(stock_code: str) -> bytes:
    """Export ReportView for a stock as PDF."""
    return await render_page_to_pdf(
        route=f"/report?code={stock_code}&auto=1",
        wait_selector=".n-tabs",
        extra_wait_ms=3000,
    )


async def export_backtest_pdf(stock_code: str, period_days: int = 1095) -> bytes:
    """Export BacktestView for a stock as PDF."""
    return await render_page_to_pdf(
        route=f"/backtest?code={stock_code}&period={period_days}&auto=1",
        wait_selector=".n-card",
        extra_wait_ms=5000,
        landscape=True,
    )


async def export_portfolio_pdf() -> bytes:
    """Export PortfolioView as PDF."""
    return await render_page_to_pdf(
        route="/portfolio?auto=1",
        wait_selector=".n-card",
        extra_wait_ms=3000,
        landscape=True,
    )
