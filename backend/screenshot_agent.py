import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://localhost:5173", wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)  # 等待 React 渲染
        await page.screenshot(path="agent_screenshot.png", full_page=False)
        print("Screenshot saved to agent_screenshot.png")
        await browser.close()

asyncio.run(main())
