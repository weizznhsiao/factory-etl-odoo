"""
Adidas order parser — handles .xlsb files from Adidas (PO LIST sheet).
"""

from __future__ import annotations
import re
import io
from typing import Optional
import pandas as pd

import logging
from ..utils import find_col_idx, normalize_size, parse_excel_date
from ..registry import register_parser
from ..models import OrderRecord

_logger = logging.getLogger(__name__)


@register_parser(brand="Adidas", extensions=[".xlsb"])
def parse_xlsb_adidas(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing Adidas XLSB file: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    f = io.BytesIO(file_bytes)
    df = pd.read_excel(f, sheet_name="PO LIST", engine="pyxlsb", header=None)

    header_row_idx: Optional[int] = None
    for idx, row in df.iterrows():
        row_vals = [str(x).strip().lower() for x in row]
        if "po #" in row_vals and "material" in row_vals:
            header_row_idx = idx
            break

    if header_row_idx is None:
        _logger.warning(f"Could not find header row in Adidas file: {filename}")
        return records

    headers = [str(x).strip() for x in df.iloc[header_row_idx]]
    po_idx = find_col_idx(headers, ["po #"])
    date_idx = find_col_idx(headers, ["original", "po date"])
    target_idx = find_col_idx(headers, ["target date", "delivery date"])
    article_idx = find_col_idx(headers, ["article"])
    model_idx = find_col_idx(headers, ["model"])
    gender_idx = find_col_idx(headers, ["gender"])
    mat_idx = find_col_idx(headers, ["material"])
    desc_idx = find_col_idx(headers, ["material name\n(long", "material name (long", "material name\n(long ..."])
    qty_idx = find_col_idx(headers, ["po q'ty", "po qty", "quantity"])
    price_idx = find_col_idx(headers, ["net price"])
    per_idx = find_col_idx(headers, ["per"])

    vertical_records: list[dict] = []
    for idx in range(header_row_idx + 1, df.shape[0]):
        row = df.iloc[idx]
        po_val = str(row.iloc[po_idx]).strip() if po_idx is not None else ""
        if not po_val or po_val == "nan" or "total" in po_val.lower() or "grand" in po_val.lower():
            continue

        mat_val = str(row.iloc[mat_idx]).strip() if mat_idx is not None else ""
        desc_val = str(row.iloc[desc_idx]).strip() if desc_idx is not None else ""

        size_name: Optional[str] = None
        if desc_val and desc_val != "nan":
            last_token = desc_val.split()[-1]
            match = re.match(r'^(\d+)(t?)$', last_token.lower())
            if match:
                num = float(match.group(1))
                half = 0.5 if match.group(2) == 't' else 0.0
                size_name = f"{num + half:.1f}"

        if not size_name:
            grid_idx = find_col_idx(headers, ["grid"])
            if grid_idx is not None:
                grid_val = str(row.iloc[grid_idx]).strip()
                if grid_val and grid_val != "nan":
                    size_name = normalize_size(grid_val)

        if not size_name:
            continue

        qty = float(row.iloc[qty_idx]) if qty_idx is not None and pd.notna(row.iloc[qty_idx]) else 0.0
        if qty <= 0:
            continue

        net_price = float(row.iloc[price_idx]) if price_idx is not None and pd.notna(row.iloc[price_idx]) else 0.0
        per_val = float(row.iloc[per_idx]) if per_idx is not None and pd.notna(row.iloc[per_idx]) else 1.0
        price = net_price / per_val if per_val > 0 else net_price

        date_val = row.iloc[date_idx] if date_idx is not None else ""
        order_date = parse_excel_date(date_val)

        target_val = row.iloc[target_idx] if target_idx is not None else ""
        delivery_date = parse_excel_date(target_val)

        article = str(row.iloc[article_idx]).strip() if article_idx is not None else ""
        model = str(row.iloc[model_idx]).strip() if model_idx is not None else ""
        gender = str(row.iloc[gender_idx]).strip() if gender_idx is not None else ""

        vertical_records.append({
            "PO": po_val,
            "Date": order_date,
            "Model": model,
            "Material": mat_val,
            "ProductCode": article if article else mat_val,
            "Description": desc_val,
            "Price": price,
            "DeliveryDate": delivery_date,
            "CustomerCode": customer_code,
            "Gender": gender,
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
