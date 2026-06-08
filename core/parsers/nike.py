"""
Nike order parser — handles PDF files from Nike.
"""

from __future__ import annotations
import re
import io
from datetime import datetime
import logging

from ..utils import normalize_size
from ..registry import register_parser
from ..models import OrderRecord

_logger = logging.getLogger(__name__)


@register_parser(brand="Nike", extensions=[".pdf"])
def parse_pdf_nike(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing Nike PDF: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    import pdfplumber
    pdf_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pdf_text += page.extract_text() + "\n"

    year_match = re.search(r'Year\s*:\s*(\d{4})', pdf_text, re.IGNORECASE)
    year = year_match.group(1) if year_match else str(datetime.now().year)

    pattern = r'(\w+)\s+(\w+)\s+([A-Z0-9]+-\d{3})\s+(\w+)\s+(.*?)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)'

    vertical_records: list[dict] = []
    for line in pdf_text.split("\n"):
        match = re.search(pattern, line.strip())
        if match:
            po = match.group(1)
            mat_no = match.group(3)
            size_raw = match.group(4)
            desc = match.group(5)
            qty = float(match.group(6).replace(",", ""))
            price = float(match.group(7))

            tokens = line.strip().split()
            to_date_raw = tokens[-1]

            delivery_date = f"{year}-06-02 00:00:00"
            if "/" in to_date_raw:
                parts = to_date_raw.split("/")
                delivery_date = f"{year}-{parts[0]}-{parts[1]} 00:00:00"

            size_clean = re.sub(r'[A-Za-z]', '', size_raw)
            size_name = normalize_size(size_clean)

            if size_name:
                vertical_records.append({
                    "PO": po,
                    "Date": delivery_date,
                    "Model": desc,
                    "Material": mat_no,
                    "ProductCode": mat_no,
                    "Description": desc,
                    "Price": price,
                    "DeliveryDate": delivery_date,
                    "CustomerCode": customer_code,
                    "Gender": "",
                    "Size": size_name,
                    "Qty": qty
                })

    grouped: dict[tuple, dict[str, float]] = {}
    for r in vertical_records:
        key = (r["PO"], r["Date"], r["Model"], r["Material"], r["ProductCode"],
               r["Description"], r["Price"], r["DeliveryDate"], r["CustomerCode"], r["Gender"])
        if key not in grouped:
            grouped[key] = {}
        grouped[key][r["Size"]] = grouped[key].get(r["Size"], 0.0) + r["Qty"]

    for key, size_qtys in grouped.items():
        po, order_date, model, mat, prod_code, desc, price, deliv_date, cust_code, gender = key
        records.append(OrderRecord(
            PO=po,
            Date=order_date,
            Model=model,
            Material=mat,
            ProductCode=prod_code,
            Description=desc,
            Price=price,
            DeliveryDate=deliv_date,
            CustomerCode=cust_code,
            Gender=gender,
            Sizes=size_qtys,
        ))

    return records
