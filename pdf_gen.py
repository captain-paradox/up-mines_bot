import os
import inspect
import base64
import logging
from io import BytesIO
import qrcode

from playwright.async_api import async_playwright
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from PyPDF2 import PdfReader, PdfWriter

# ---------- Logging Setup ----------
logging.basicConfig(
    format='[%(asctime)s] %(levelname)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
# -----------------------------------

from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from io import BytesIO
import base64
import re

def draw_data(c, data):
    c.setFont("Helvetica-Bold", 6)

    def draw_wrapped_text(x, y, text, max_words=4, line_spacing=6):
        words = text.split()
        lines = []

        # Split text into chunks of max_words
        for i in range(0, len(words), max_words):
            lines.append(" ".join(words[i:i + max_words]))

        # Draw up to 3 lines
        for i, line in enumerate(lines[:3]):
            c.drawString(x, y - i * line_spacing, line)

    # Top section
    raw_emM11 = data.get("emM11", "")
    clean_emM11 = re.sub(r"[^\d]", "", raw_emM11)
    c.drawString(245, 716.5, clean_emM11)
    c.drawString(372, 717.5, data.get("lessee_id", ""))

    draw_wrapped_text(100, 707, data.get("lessee_name", ""))
    c.drawString(260, 707, data.get("lessee_mobile", ""))
    draw_wrapped_text(435, 708, data.get("lease_details", ""))

    # Middle section
    c.drawString(100, 690, data.get("tehsil", ""))
    c.drawString(260, 690, data.get("district", ""))
    c.drawString(405, 682, data.get("qty", ""))

    draw_wrapped_text(100, 672.5, data.get("mineral", ""))
    c.drawString(265, 672.5, data.get("loading_from", ""))
    c.drawString(435, 672.5, data.get("destination", ""))

    c.drawString(60, 641, data.get("distance", ""))
    c.drawString(250, 648, data.get("generated_on", ""))
    c.drawString(435, 648, data.get("valid_upto", ""))

    c.drawString(110, 625, data.get("travel_duration", ""))
    c.drawString(260, 630, data.get("destination_district", ""))
    c.drawString(435, 630, data.get("destination_state", ""))

    c.drawString(195, 607, data.get("pit_value", ""))
    # c.drawString(330, 613, data.get(""))

    c.drawString(150, 592, data.get("registration_number", ""))
    c.drawString(160, 583, data.get("driver_mobile", ""))
    c.drawString(320, 592, data.get("vehicle_type", ""))
    c.drawString(320, 583, data.get("driver_dl", ""))
    c.drawString(470, 592, data.get("driver_name", ""))

    if "qr_code_base64" in data:
        try:
            qr_data = base64.b64decode(data["qr_code_base64"].split(",")[1])
            qr_image = ImageReader(BytesIO(qr_data))

            # === QR and layout settings ===
            qr_size = 40  # QR size
            padding_top = 5
            padding_bottom = 5
            padding_left = 5
            padding_right = 5

            bg_color = (1, 1, 1)  # pure white background  # light gray background (R, G, B)
            PAGE_WIDTH, PAGE_HEIGHT = A4
            margin_right = 70
            margin_top = 80

            # Position of QR image (bottom-left of QR)
            x_qr = PAGE_WIDTH - qr_size - margin_right
            y_qr = PAGE_HEIGHT - qr_size - margin_top

            # Position and size of background rectangle
            bg_x = x_qr - padding_left
            bg_y = y_qr - padding_bottom
            bg_width = qr_size + padding_left + padding_right
            bg_height = qr_size + padding_top + padding_bottom

            # === Draw background rectangle ===
            c.setFillColorRGB(*bg_color)
            c.rect(bg_x, bg_y, bg_width, bg_height, fill=True, stroke=False)

            # === Draw QR code on top ===
            c.drawImage(
                qr_image,
                x_qr,
                y_qr,
                width=qr_size,
                height=qr_size,
                preserveAspectRatio=True,
                mask='auto'
            )

        except Exception as e:
            logger.warning(f"⚠️ QR drawing failed: {e}")

def generate_pdf(data, template_path, output_path):
    overlay_stream = BytesIO()
    c = canvas.Canvas(overlay_stream, pagesize=A4)
    draw_data(c, data)
    c.save()
    overlay_stream.seek(0)

    bg_reader = PdfReader(template_path)
    ov_reader = PdfReader(overlay_stream)
    writer = PdfWriter()

    page = bg_reader.pages[0]
    page.merge_page(ov_reader.pages[0])
    writer.add_page(page)

    with open(output_path, "wb") as f:
        writer.write(f)

    # Now draw QR code on top
    # if "qr_code_base64" in data:
    #     draw_qr_after_merge(output_path, data["qr_code_base64"])

    # logger.info(f"✅ Generated PDF at: {output_path}")

async def create_qr_image_base64(tp_num, url):
    logger.info(f"🧾 Generating QR for TP: {tp_num}")
    
    if not url or not isinstance(url, str):
        logger.error(f"❌ Invalid URL for TP {tp_num}: {url!r}")
        raise ValueError(f"Invalid URL passed to QR generator for TP {tp_num}")

    try:
        logger.debug(f"🔗 QR URL for TP {tp_num}: {url}")
        img = qrcode.make(url)
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_bytes = buffered.getvalue()

        if not img_bytes:
            logger.error(f"❌ QR image generation failed for TP {tp_num}: no bytes returned")
            raise ValueError(f"QR image generation failed for TP {tp_num}")

        base64_str = base64.b64encode(img_bytes).decode()
        logger.info(f"✅ QR generated successfully for TP {tp_num}")
        return f"data:image/png;base64,{base64_str}"

    except Exception as e:
        logger.exception(f"❌ Exception while generating QR for TP {tp_num}: {e}")
        raise

async def pdf_gen(tp_num_list, output_dir="pdf",template_path="form_template.pdf", log_callback=None, send_pdf_callback=None):
    if not tp_num_list:
        logger.info("ℹ️ No TP numbers provided.")
        return []

    os.makedirs("pdf", exist_ok=True)
    all_pdfs = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()

        for tp_num in tp_num_list:
            tp_num = str(tp_num)
            logger.info(f"📦 Processing TP: {tp_num}")
            try:
                page = await context.new_page()
                url = f"https://upmines.upsdc.gov.in/Registration/PrintRegistrationFormVehicleCheckValidOrNot.aspx?eId={tp_num}"
                await page.goto(url, timeout=20000)

                lbl_etpNo = await page.locator("#lbl_etpNo").inner_text()
                if tp_num not in lbl_etpNo:
                    raise ValueError(f"Mismatch: expected {tp_num}, got {lbl_etpNo}")

                data = {    
                            "distance": await page.locator('#lbl_distrance').inner_text(),
                            "destination_state": "Uttar Pradesh",
                            "emM11": tp_num,
                            "lessee_name": await page.locator('#lbl_name_of_lease').inner_text(),
                            "lessee_mobile": await page.locator("#lbl_mobile_no").inner_text(),
                            "serial_number": await page.locator("#lbl_SerialNumber").inner_text(),
                            "lessee_id": await page.locator("#lbl_LeaseId").inner_text(),
                            "lease_details": await page.locator('#lbl_leaseDetails').inner_text(),
                            "tehsil": await page.locator("#lbl_tehsil").inner_text(),
                            "district": await page.locator("#lbl_district").inner_text(),
                            "qty": await page.locator("#lbl_qty_to_Transport").inner_text(),
                            "mineral": await page.locator("#lbl_type_of_mining_mineral").inner_text(),
                            "loading_from": await page.locator("#lbl_loadingfrom").inner_text(),
                            "destination": await page.locator("#lbl_destination_address").inner_text(),
                            "destination_district": await page.locator("#lbl_destination_district").inner_text(),
                            "generated_on": await page.locator("#txt_etp_generated_on").inner_text(),
                            "valid_upto": await page.locator("#txt_etp_valid_upto").inner_text(),
                            "travel_duration": await page.locator("#lbl_travel_duration").inner_text(),
                            "pit_value": await page.locator("#pit").inner_text(),
                            "registration_number": await page.locator("#lbl_registraton_number_of_vehicle").inner_text(),
                            "driver_name": await page.locator("#lbl_name_of_driver").inner_text(),
                            "driver_mobile": await page.locator("#lbl_mobile_number_of_driver").inner_text(),
                            "vehicle_type": "14 TYRE TRUCK",                       
                        }

                data["qr_code_base64"] = await create_qr_image_base64(tp_num, url)

                output_path = f"pdf/{tp_num}.pdf"
                generate_pdf(data, template_path, output_path)
                all_pdfs.append((tp_num, output_path))

                logger.info(f"✅ Successfully processed TP: {tp_num}")

                if send_pdf_callback:
                    if inspect.iscoroutinefunction(send_pdf_callback):
                        await send_pdf_callback(output_path, tp_num)
                    else:
                        send_pdf_callback(output_path, tp_num)

                await page.close()

            except Exception as e:
                logger.error(f"❌ Failed TP {tp_num}: {e}")

        await browser.close()

    return all_pdfs
