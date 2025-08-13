from playwright.async_api import Page
from pdf_gen import pdf_gen
import os

async def process_emm11(
    page: Page,
    emm11_numbers_list,
    log_callback=None,
    send_pdf_callback=None,
    user_id=None
):
    """
    Process eMM11 numbers and optionally send results as a PDF via Telegram.

    Args:
        page (Page): Playwright page instance.
        emm11_numbers_list (list): List of eMM11 numbers to check.
        log_callback (coroutine): Async function for sending logs to user.
        send_pdf_callback (coroutine): Async function for sending PDF to user.
        user_id (int): Telegram user ID (required for sending files).
    """
    async def log(msg):
        if log_callback:
            await log_callback(msg)
        else:
            print(msg)

    try:
        master_menu = page.locator("//a[normalize-space()='Master Entries']")
        await master_menu.wait_for(state="visible", timeout=6000)
        await master_menu.click()
        await page.wait_for_timeout(1000)

        submenu = page.locator("//a[normalize-space()='Apply for eFormC Quantity by Transit Pass Number']")
        await submenu.wait_for(state="visible", timeout=6000)
        await submenu.click()
        await page.wait_for_timeout(1000)

        await page.select_option("#ContentPlaceHolder1_ddl_LicenseeID", index=1)
        await page.click("#ContentPlaceHolder1_RbtWise_0")
        await page.wait_for_timeout(1500)

        tp_num_list = []
        for tp_num in filter(None, emm11_numbers_list):
            try:
                await page.fill("#ContentPlaceHolder1_txt_eMM11No", str(tp_num))
                await page.click("#ContentPlaceHolder1_btnProceed")
                await page.wait_for_timeout(1000)

                error_locator = page.locator("#ContentPlaceHolder1_ErrorLbl")
                if await error_locator.is_visible():
                    error_text = await error_locator.inner_text()
                    if "not generated for storage license" in error_text:
                        await log(f"{tp_num} : ❌ Unused")
                        tp_num_list.append(str(tp_num))
                else:
                    await log(f"TP Number: {tp_num} ✅ No error detected or form submitted.")
            except Exception as e:
                await log(f"⚠️ TP Number: {tp_num} - Failed to process due to: {e}")

        # if tp_num_list:
        #     await log(f"📄 Generating PDF for {len(tp_num_list)} eligible TP numbers...")
        #     # pdf_path = await pdf_gen(tp_num_list)

        #     if send_pdf_callback and user_id:
        #         await send_pdf_callback(user_id, pdf_path)

        #     # Optional cleanup
        #     if os.path.exists(pdf_path):
        #         os.remove(pdf_path)
        # else:
        #     await log("ℹ️ No eligible TP numbers found for PDF generation.")

    except Exception as e:
        print("Error:",e)
        # await log(f"🔥 Fatal error in process_emm11: {e}")
