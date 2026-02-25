"""Phase 14 Task 1: AI Signal Commentator — Playwright + Gemini Web UI.

CTO: "讓 AI 用一句話戳穿信號的本質"
Architect APPROVED: Context payload minimized (natural language, NOT JSON),
    deterministic fallback with 80% direction consistency,
    prompt role "冷靜、毒舌但極度看重風險回報比的台股資深交易員",
    headless Playwright mode.

Joe directive: Use Playwright browser automation to communicate with Gemini Web UI,
    NOT Gemini API — no rate limit issue.

Flow:
  1. Build natural-language context for top signals
  2. Send to Gemini Web UI via Playwright (headless, persistent login)
  3. Parse per-stock one-line comments
  4. Fallback: deterministic template (Energy + RS + Tier logic)
"""

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GEMINI_URL = "https://gemini.google.com/app"
BROWSER_STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "browser_state"

# [VERIFIED: PROMPT_V1] — Architect approved role
AI_PROMPT_V1 = (
    "你是一位冷靜、毒舌但極度看重風險回報比的台股資深交易員（20年經驗）。\n"
    "請針對以下每檔股票，用一句話（30字以內）給出你的即時反應。\n"
    "語氣要求：直白、不客套、抓重點。看到風險就大聲說。\n\n"
    "格式：每檔一行，格式為「股票代碼: 評語」\n"
    "範例：2330: RS強但量能過熱，追高送命\n\n"
    "以下是今日信號：\n"
)


def _build_context_payload(signals: list[dict]) -> str:
    """Build minimized natural language context for Gemini.

    Architect mandate: Natural language, NOT JSON.
    """
    lines = []
    for s in signals:
        code = s.get("stock_code", "")
        name = s.get("name", "")
        tier = s.get("tier", "")
        confidence = s.get("confidence_score", 0)
        grade = s.get("confidence_grade", "LOW")
        rs = s.get("rs_rating", 0)
        d21_mean = s.get("d21_mean")
        worst = s.get("worst_case_pct")
        industry = s.get("industry", "")

        parts = [f"{code} {name} ({industry}) — {tier}"]
        parts.append(f"信心{confidence}({grade})")
        parts.append(f"RS{rs:.0f}")
        if d21_mean is not None:
            parts.append(f"預期{d21_mean * 100:+.1f}%")
        if worst is not None:
            parts.append(f"最差{worst:.1f}%")

        energy_warns = s.get("energy_warnings", [])
        if energy_warns:
            parts.append(f"警示:{';'.join(energy_warns)}")

        if s.get("divergence_warning"):
            parts.append("Block分歧")

        lines.append(", ".join(parts))

    return AI_PROMPT_V1 + "\n".join(lines)


def _deterministic_fallback(signals: list[dict]) -> dict[str, str]:
    """Deterministic fallback when Gemini is unreachable.

    Architect mandate: 80% direction consistency with AI output.
    Logic: Energy > Risk/Reward > Confidence + Tier.
    """
    comments: dict[str, str] = {}
    for s in signals:
        code = s.get("stock_code", "")
        tier = s.get("tier", "")
        confidence = s.get("confidence_score", 0)
        rs = s.get("rs_rating", 0)
        energy_overheat = s.get("energy_overheat", False)
        energy_weak = s.get("energy_weak_volume", False)
        worst = s.get("worst_case_pct")
        d21_mean = s.get("d21_mean")

        # Priority 1: Energy warnings
        if energy_overheat:
            comments[code] = "量能過熱，追高風險大，等回測再說"
        elif energy_weak:
            comments[code] = "突破沒量，假動作機率高"
        # Priority 2: Risk/reward red flags
        elif worst is not None and worst < -10:
            comments[code] = f"最差{worst:.0f}%，風報比差，pass"
        elif d21_mean is not None and d21_mean < -0.02:
            comments[code] = "歷史同型態偏空，小心多頭陷阱"
        # Priority 3: Positive signals
        elif confidence >= 70 and tier == "sniper":
            if rs >= 90:
                comments[code] = "強勢股標準進場，控制倉位就好"
            else:
                comments[code] = "模型信心足，值得一試"
        elif confidence >= 40:
            comments[code] = "中等機會，倉位減半控風險"
        else:
            comments[code] = "數據不夠，觀察就好別衝動"

    return comments


async def _query_gemini_playwright(prompt: str, timeout_s: int = 90) -> Optional[str]:
    """Use Playwright to send prompt to Gemini Web UI and get response.

    Architect: Headless mode, persistent browser state for login.
    Joe: Use Playwright instead of API — no rate limit.

    Requires:
      1. `pip install playwright && playwright install chromium`
      2. First-time: run `setup_gemini_login()` to save login cookies
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("playwright not installed — pip install playwright && playwright install chromium")
        return None

    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_DIR),
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()

            # Navigate to Gemini
            await page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)

            # Check if we're logged in (look for input area)
            input_area = None
            for selector in [
                'div.ql-editor[contenteditable="true"]',
                'rich-textarea div[contenteditable="true"]',
                'div[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
            ]:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000)
                    if el:
                        input_area = el
                        break
                except Exception:
                    continue

            if not input_area:
                logger.warning("Gemini input area not found — login may have expired")
                await browser.close()
                return None

            # Clear and type the prompt
            await input_area.click()
            # Use keyboard to type (more reliable than fill for contenteditable)
            await page.keyboard.press("Control+a")
            await page.keyboard.press("Delete")
            await input_area.fill(prompt)
            await page.wait_for_timeout(500)

            # Click send button
            sent = False
            for btn_selector in [
                'button[aria-label*="Send"]',
                'button[aria-label*="傳送"]',
                'button[data-at="send"]',
                'button.send-button',
            ]:
                try:
                    btn = page.locator(btn_selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        sent = True
                        break
                except Exception:
                    continue

            if not sent:
                # Fallback: press Enter
                await page.keyboard.press("Enter")

            # Wait for response to appear and stabilize
            await page.wait_for_timeout(5000)

            # Poll for response completion (check if Gemini is still typing)
            max_wait = timeout_s * 1000  # ms
            waited = 5000
            poll_interval = 3000
            prev_text = ""

            while waited < max_wait:
                # Check for response text
                response_text = await page.evaluate("""() => {
                    // Try multiple selectors for response
                    const selectors = [
                        '.model-response-text',
                        '.response-container',
                        '.message-content',
                        '[data-message-author-role="model"]',
                    ];
                    for (const sel of selectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length > 0) {
                            return els[els.length - 1].innerText;
                        }
                    }
                    return '';
                }""")

                if response_text and response_text == prev_text and len(response_text) > 20:
                    # Response stabilized
                    await browser.close()
                    return response_text.strip()

                prev_text = response_text
                await page.wait_for_timeout(poll_interval)
                waited += poll_interval

            # Timeout — return whatever we have
            if prev_text:
                await browser.close()
                return prev_text.strip()

            await browser.close()
            return None

    except Exception as e:
        logger.warning("Gemini Playwright query failed: %s", e)
        return None


def _parse_gemini_response(text: str, stock_codes: list[str]) -> dict[str, str]:
    """Parse Gemini's response into per-stock comments.

    Expected format: "股票代碼: 評語" per line.
    Robust parsing: handles bullet points, markdown, extra whitespace.
    """
    comments: dict[str, str] = {}
    if not text:
        return comments

    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip()
        # Strip markdown bullets (e.g., "- ", "* ", "1. ") but NOT stock codes
        line = re.sub(r"^(?:[\-\*]\s+|\d+\.\s+)", "", line)
        if not line:
            continue

        for code in stock_codes:
            if code in line:
                # Extract comment after the code
                parts = line.split(code, 1)
                if len(parts) > 1:
                    comment = parts[1].strip()
                    # Strip separator characters
                    comment = re.sub(r"^[\s:：\-\|]+", "", comment).strip()
                    if comment and len(comment) >= 3:
                        comments[code] = comment[:50]  # Cap at 50 chars
                        break

    return comments


def get_ai_comments(signals: list[dict]) -> dict[str, str]:
    """Get AI comments for signals — Gemini first, fallback if unreachable.

    Returns: {stock_code: comment_string}
    """
    if not signals:
        return {}

    stock_codes = [s.get("stock_code", "") for s in signals]

    # Try Gemini via Playwright
    try:
        prompt = _build_context_payload(signals)
        loop = asyncio.new_event_loop()
        response = loop.run_until_complete(_query_gemini_playwright(prompt))
        loop.close()

        if response:
            comments = _parse_gemini_response(response, stock_codes)
            if len(comments) >= len(signals) * 0.5:  # At least 50% parsed
                logger.info(
                    "AI Commentator: Gemini returned %d/%d comments",
                    len(comments), len(signals),
                )
                # Fill missing with fallback
                fallback = _deterministic_fallback(signals)
                for code in stock_codes:
                    if code not in comments:
                        comments[code] = fallback.get(code, "")
                return comments
            else:
                logger.warning(
                    "AI Commentator: Gemini parse rate low (%d/%d), using fallback",
                    len(comments), len(signals),
                )
    except Exception as e:
        logger.warning("AI Commentator: Gemini failed, using fallback: %s", e)

    # Fallback
    return _deterministic_fallback(signals)


def get_single_comment(stock_code: str, context: dict) -> str:
    """Get AI comment for a single stock (for "Ask AI" button).

    Args:
        stock_code: Stock code
        context: Signal dict with tier, confidence_score, rs_rating, etc.

    Returns: One-line comment string.
    """
    signals = [{**context, "stock_code": stock_code}]
    comments = get_ai_comments(signals)
    return comments.get(stock_code, "暫無評語")


def update_signal_comments(comments: dict[str, str]) -> int:
    """Update ai_comment column in signal_log DB.

    Returns: number of rows updated.
    """
    if not comments:
        return 0

    import sqlite3
    from analysis.signal_log import DB_PATH, _get_conn

    conn = _get_conn()
    updated = 0
    try:
        for code, comment in comments.items():
            cursor = conn.execute(
                """UPDATE trade_signals_log
                   SET ai_comment = ?
                   WHERE stock_code = ? AND signal_date = date('now')""",
                (comment, code),
            )
            updated += cursor.rowcount
        conn.commit()
    finally:
        conn.close()

    logger.info("AI Commentator: updated %d signal comments", updated)
    return updated


def setup_gemini_login():
    """Interactive setup: open browser for user to log into Gemini.

    Run this once manually:
        python -c "from analysis.ai_commentator import setup_gemini_login; setup_gemini_login()"

    After login, browser state is saved to data/browser_state/ for headless use.
    """
    import asyncio

    async def _login():
        from playwright.async_api import async_playwright

        BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_STATE_DIR),
                headless=False,  # Visible for manual login
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto(GEMINI_URL)

            print("\n" + "=" * 60)
            print("Please log into Google/Gemini in the browser window.")
            print("After login, verify you can see the Gemini chat input.")
            print("Then press Enter here to save the session...")
            print("=" * 60)
            input()

            await browser.close()
            print(f"Browser state saved to: {BROWSER_STATE_DIR}")
            print("Headless AI Commentator is now ready.")

    asyncio.run(_login())
