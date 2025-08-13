# fetch_emm11_data.py
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://upmines.upsdc.gov.in/Registration/PrintRegistrationFormVehicleCheckValidOrNot.aspx?eId={}"
HEADLESS = True
CONCURRENCY_LIMIT = 10

async def fetch_single_emm11(playwright, emm11_num, district, log=print):
    url = BASE_URL.format(emm11_num)
    browser = await playwright.chromium.launch(headless=HEADLESS)
    page = await browser.new_page()

    try:
        await page.goto(url, timeout=10000)
        await page.wait_for_selector("#lbl_destination_district", timeout=5000)
        district_text = await page.locator("#lbl_destination_district").inner_text()
        quantity = await page.locator("#lbl_qty_to_Transport").inner_text()
        address = await page.locator("#lbl_destination_address").inner_text()
        generated_on = await page.locator("#txt_etp_generated_on").inner_text()

        if district_text.strip().upper() == district.upper():
            return {
                "eMM11_num": emm11_num,
                "destination_district": district_text.strip(),
                "quantity_to_transport": quantity.strip(),
                "destination_address": address.strip(),
                "generated_on": generated_on.strip()
            }

    except PlaywrightTimeoutError:
        log(f"[{emm11_num}] Timeout while fetching data.")
    except Exception as e:
        log(f"[{emm11_num}] Error: {e}")
    finally:
        await browser.close()

    return None

async def fetch_emm11_data(start_num, end_num, district, data_callback=None, log=print):
    results = []
    async with async_playwright() as playwright:
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

        async def limited_fetch(num):
            async with semaphore:
                result = await fetch_single_emm11(playwright, num, district, log=log)
                if result:
                    if data_callback:
                        await data_callback(result)
                    return result
                return None

        tasks = [limited_fetch(i) for i in range(start_num, end_num + 1)]
        all_results = await asyncio.gather(*tasks)

        if not data_callback:
            results = [r for r in all_results if r]
            return results

    return []
