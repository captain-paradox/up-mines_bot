import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import easyocr

from emm11_processor import process_emm11

reader = easyocr.Reader(['en'], gpu=False)

async def login_to_website(data, update, context,log_callback=None):
    """Login and process eMM11 data for a single user session."""
    user_id = update.effective_user.id
    log_callback = lambda msg: asyncio.create_task(
        context.bot.send_message(chat_id=user_id, text=msg)
    )

    aadhar_number = "855095518363"
    password = "Nic@1616"
    max_attempts = 5

    await log_callback("🔄 Starting login process...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context_browser = await browser.new_context()
        page = await context_browser.new_page()

        try:
            await page.goto("https://upmines.upsdc.gov.in/DefaultLicense.aspx", timeout=20000)
        except PlaywrightTimeoutError:
            await log_callback("❌ Failed to load login page. Server may be down.")
            await browser.close()
            return

        await page.wait_for_timeout(2000)
        login_success = False

        for attempt in range(1, max_attempts + 1):
            await log_callback(f"Attempt {attempt} of {max_attempts}...")

            try:
                await page.fill("#ContentPlaceHolder1_txtAadharNumber", aadhar_number)
                await page.fill("#ContentPlaceHolder1_txtPassword", password)

                captcha_elem = await page.query_selector("#Captcha")
                captcha_bytes = await captcha_elem.screenshot()
                result = reader.readtext(captcha_bytes, detail=0)

                captcha_text = result[0].strip() if result else ""
                if not captcha_text.isdigit():
                    await log_callback("⚠️ Captcha not recognized, retrying...")
                    await page.reload()
                    await page.wait_for_timeout(1500)
                    continue

                await page.fill("#ContentPlaceHolder1_txtCaptcha", captcha_text)
                await page.click("#ContentPlaceHolder1_btn_captcha")

                try:
                    await page.wait_for_selector('#pnlMenuEng', timeout=5000)
                    login_success = True

                    async def handle_dialog(dialog):
                        await dialog.accept()

                    page.once("dialog", handle_dialog)
                    await log_callback("✅ Login successful!")
                    await page.wait_for_timeout(1500)
                    break

                except PlaywrightTimeoutError:
                    await log_callback("⚠️ Login failed, retrying...")
                    await page.reload()
                    await page.wait_for_timeout(2000)

            except Exception as e:
                await log_callback(f"⚠️ Error: {e}, retrying...")
                await page.reload()
                await page.wait_for_timeout(2000)

        if not login_success:
            await log_callback("❌ Could not log in after multiple attempts.")
            await browser.close()
            return

        try:
            emm11_numbers_list = [record["eMM11_num"] for record in data if "eMM11_num" in record]
            await process_emm11(page, emm11_numbers_list, log_callback)
        except Exception as e:
            await log_callback(f"❌ Error during eMM11 processing: {e}")

        await browser.close()
        await log_callback("✅ Process completed.")
