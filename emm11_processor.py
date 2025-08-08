from playwright.async_api import Page
from pdf_gen import pdf_gen


async def process_emm11(page: Page, emm11_numbers_list, log_callback=print, send_pdf_callback=None):
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

                    tp_num = str(tp_num)
                    if "not generated for storage license" in error_text:
                        log_callback(f"{tp_num}\n : Unused")
                        tp_num_list.append(tp_num)
                else:
		   
                    log_callback(f"TP Number: {tp_num}\n✅ No error detected or form submitted.")
            except Exception as e:
                log_callback(f"⚠️ TP Number: {tp_num} - Failed to process due to: {e}")

        if tp_num_list:
            print("pdf")
            # log_callback(f"📄 Preparing to generate PDFs for {len(tp_num_list)} eligible TP numbers.")
            return tp_num_list
        else:
            log_callback("ℹ️ No eligible TP numbers found for PDF generation.")

    except Exception as e:
        log_callback(f"🔥 Fatal error in process_emm11: {e}")
