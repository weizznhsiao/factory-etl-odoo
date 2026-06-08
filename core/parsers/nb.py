"""
New Balance order parsers.
"""

from __future__ import annotations
import os
import re
import io
from typing import Optional
import pandas as pd
import logging

from ..utils import find_col_idx, find_val_near_label, normalize_size, parse_excel_date
from ..registry import register_parser
from ..models import OrderRecord

_logger = logging.getLogger(__name__)


def _is_single_sheet_xls(file_bytes: bytes, sheet_names: list[str]) -> bool:
    return "NB訂購單" in sheet_names


def _is_two_sheet_xls(file_bytes: bytes, sheet_names: list[str]) -> bool:
    return any("lot" in s.lower() or "detail" in s.lower() for s in sheet_names)


@register_parser(brand="NB", extensions=[".xls"], sheet_predicate=_is_two_sheet_xls)
def parse_xls_nb_two_sheets(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing NB two-sheet XLS file: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    f = io.BytesIO(file_bytes)
    xl = pd.ExcelFile(f, engine="xlrd")
    sheet_names = xl.sheet_names

    cover_sheet = sheet_names[0]
    df_cover = pd.read_excel(xl, sheet_name=cover_sheet, header=None)

    size_sheet = [s for s in sheet_names if "lot" in s.lower() or "detail" in s.lower()][0]
    df_size = pd.read_excel(xl, sheet_name=size_sheet, header=None)

    po = find_val_near_label(df_cover, ["P.O.NO.:", "PO NO:", "PO#", "PO NO"])
    if not po:
        po = os.path.basename(filename).split(".")[0]

    date_val = find_val_near_label(df_cover, ["DATE:", "Order Date:", "Date"])
    date_str = parse_excel_date(date_val)

    code_map: dict[str, dict] = {}
    header_row_idx: Optional[int] = None
    for idx, row in df_cover.iterrows():
        row_vals = [str(x).strip().lower() for x in row]
        if "code" in row_vals and ("u/p" in row_vals or "price" in row_vals):
            header_row_idx = idx
            break

    if header_row_idx is not None:
        headers = [str(x).strip() for x in df_cover.iloc[header_row_idx]]
        c_idx = find_col_idx(headers, ["code"])
        up_idx = find_col_idx(headers, ["u/p", "price", "unit price"])
        rtd_idx = find_col_idx(headers, ["rtd", "delivery", "etd"])
        model_idx = find_col_idx(headers, ["model"])
        desc_idx = find_col_idx(headers, ["description of goods", "description"])

        for idx in range(header_row_idx + 1, df_cover.shape[0]):
            row = df_cover.iloc[idx]
            code_val = str(row.iloc[c_idx]).strip() if c_idx is not None else ""
            if not code_val or code_val == "nan" or "total" in code_val.lower():
                continue

            price = float(row.iloc[up_idx]) if up_idx is not None and pd.notna(row.iloc[up_idx]) else 0.0
            rtd = parse_excel_date(row.iloc[rtd_idx]) if rtd_idx is not None else date_str
            model = str(row.iloc[model_idx]).strip() if model_idx is not None else ""
            desc = str(row.iloc[desc_idx]).strip() if desc_idx is not None else ""

            code_map[code_val] = {
                "price": price,
                "delivery_date": rtd,
                "model": model,
                "description": desc
            }

    size_header_idx: Optional[int] = None
    for idx, row in df_size.iterrows():
        row_vals = [str(x).strip().lower() for x in row]
        if "code" in row_vals and ("model name" in row_vals or "product code" in row_vals):
            size_header_idx = idx
            break

    if size_header_idx is not None:
        headers = [str(x).strip() for x in df_size.iloc[size_header_idx]]
        c_idx = find_col_idx(headers, ["code"])
        model_idx = find_col_idx(headers, ["model name", "model"])
        prod_idx = find_col_idx(headers, ["product code", "product"])
        gender_idx = find_col_idx(headers, ["gender"])

        size_cols: list[tuple[int, Optional[str]]] = []
        for col_idx, h in enumerate(headers):
            h_clean = str(h).replace("'", "").replace('"', '').strip()
            if h_clean.endswith('#') or (h_clean.replace('.', '', 1).isdigit() and float(h_clean) < 20):
                size_cols.append((col_idx, normalize_size(h_clean)))

        for idx in range(size_header_idx + 1, df_size.shape[0]):
            row = df_size.iloc[idx]
            code_val = str(row.iloc[c_idx]).strip() if c_idx is not None else ""
            prod_val = str(row.iloc[prod_idx]).strip() if prod_idx is not None else ""

            if (not code_val or code_val == "nan") and idx > size_header_idx + 1:
                if (prod_val and prod_val != "nan") or (model_idx is not None and str(row.iloc[model_idx]).strip() != "nan"):
                    for p_idx in range(idx - 1, size_header_idx, -1):
                        prev_code = str(df_size.iloc[p_idx, c_idx]).strip()
                        if prev_code and prev_code != "nan":
                            code_val = prev_code
                            break

            if not code_val or code_val == "nan" or "total" in code_val.lower():
                continue

            info = code_map.get(code_val, {"price": 0.0, "delivery_date": date_str, "model": "", "description": ""})

            row_model = str(row.iloc[model_idx]).strip() if model_idx is not None and pd.notna(row.iloc[model_idx]) and str(row.iloc[model_idx]).strip() != "nan" else info.get("model", "")
            prod_code = prod_val if prod_val != "nan" else ""
            gender = str(row.iloc[gender_idx]).strip() if gender_idx is not None and pd.notna(row.iloc[gender_idx]) and str(row.iloc[gender_idx]).strip() != "nan" else ""

            size_qtys: dict[str, float] = {}
            for col_idx, sz_name in size_cols:
                if sz_name:
                    qty_val = row.iloc[col_idx]
                    try:
                        qty = float(qty_val)
                        if qty > 0:
                            size_qtys[sz_name] = qty
                    except (ValueError, TypeError):
                        pass

            if size_qtys:
                records.append(OrderRecord(
                    PO=str(po).strip(),
                    Date=date_str,
                    Model=row_model,
                    Material=code_val,
                    ProductCode=prod_code if prod_code else code_val,
                    Description=info.get("description", ""),
                    Price=info.get("price", 0.0),
                    DeliveryDate=info.get("delivery_date", date_str),
                    CustomerCode=customer_code,
                    Gender=gender,
                    Sizes=size_qtys,
                ))

    return records


@register_parser(brand="NB", extensions=[".xls"], sheet_predicate=_is_single_sheet_xls)
def parse_xls_nb_single_sheet(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing NB single-sheet XLS file: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    f = io.BytesIO(file_bytes)
    df = pd.read_excel(f, sheet_name=0, header=None, engine="xlrd")

    header_row_idx: Optional[int] = None
    for idx, row in df.iterrows():
        row_vals = [str(x).strip().lower() for x in row]
        if "material name" in row_vals or "material description" in row_vals or "po#" in row_vals:
            header_row_idx = idx
            break

    if header_row_idx is None:
        _logger.warning(f"Could not find header row in NB single-sheet file: {filename}")
        return records

    headers = [str(x).strip() for x in df.iloc[header_row_idx]]
    po_idx = find_col_idx(headers, ["po#"])
    date_idx = find_col_idx(headers, ["date"])
    model_idx = find_col_idx(headers, ["model name", "model"])
    style_idx = find_col_idx(headers, ["style"])
    mat_idx = find_col_idx(headers, ["mt'l code", "material code", "料號"])
    desc_idx = find_col_idx(headers, ["material name", "description"])
    price_idx = find_col_idx(headers, ["price", "單價"])
    etd_idx = find_col_idx(headers, ["etd", "delivery", "交期"])

    size_cols: list[tuple[int, Optional[str]]] = []
    for col_idx, h in enumerate(headers):
        h_clean = str(h).replace("'", "").replace('"', '').strip()
        sz = normalize_size(h_clean)
        if sz and col_idx > (mat_idx or 0):
            size_cols.append((col_idx, sz))

    for idx in range(header_row_idx + 1, df.shape[0]):
        row = df.iloc[idx]
        mat_val = str(row.iloc[mat_idx]).strip() if mat_idx is not None else ""
        po_val = str(row.iloc[po_idx]).strip() if po_idx is not None else ""

        if not mat_val or mat_val == "nan" or "total" in mat_val.lower() or "remark" in mat_val.lower():
            continue
        if not po_val or po_val == "nan":
            continue

        date_val = row.iloc[date_idx] if date_idx is not None else ""
        order_date = parse_excel_date(date_val)

        etd_val = row.iloc[etd_idx] if etd_idx is not None else ""
        delivery_date = parse_excel_date(etd_val)

        model = str(row.iloc[model_idx]).strip() if model_idx is not None else ""
        style = str(row.iloc[style_idx]).strip() if style_idx is not None else ""
        row_model = model if model else style

        desc_val = str(row.iloc[desc_idx]).strip() if desc_idx is not None else ""

        price_val = 0.0
        if price_idx is not None:
            p_raw = row.iloc[price_idx]
            try:
                price_val = float(p_raw)
            except (ValueError, TypeError):
                price_val = 0.0

        size_qtys: dict[str, float] = {}
        for col_idx, sz_name in size_cols:
            if sz_name:
                qty_val = row.iloc[col_idx]
                try:
                    qty = float(qty_val)
                    if qty > 0:
                        size_qtys[sz_name] = qty
                except (ValueError, TypeError):
                    pass

        if size_qtys:
            records.append(OrderRecord(
                PO=po_val,
                Date=order_date,
                Model=row_model,
                Material=mat_val,
                ProductCode=mat_val,
                Description=desc_val,
                Price=price_val,
                DeliveryDate=delivery_date,
                CustomerCode=customer_code,
                Gender="",
                Sizes=size_qtys,
            ))

    return records


@register_parser(brand="NB", extensions=[".xlsx"])
def parse_xlsx_nb(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing NB XLSX file: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    f = io.BytesIO(file_bytes)
    df = pd.read_excel(f, sheet_name="unload", header=None)

    header_indices: list[int] = []
    for idx, row in df.iterrows():
        row_vals = [str(x).strip().lower() for x in row]
        if "purchase#" in row_vals and "material#" in row_vals:
            header_indices.append(idx)

    for i, h_idx in enumerate(header_indices):
        next_h_idx = header_indices[i + 1] if i + 1 < len(header_indices) else df.shape[0]

        headers = [str(x).strip() for x in df.iloc[h_idx]]
        po_idx = find_col_idx(headers, ["purchase#"])
        mat_idx = find_col_idx(headers, ["material#"])
        desc_idx = find_col_idx(headers, ["material description"])
        etd_idx = find_col_idx(headers, ["req_etd"])
        planning_idx = find_col_idx(headers, ["planning#"])

        size_cols: list[tuple[int, Optional[str]]] = []
        for col_idx, h in enumerate(headers):
            h_clean = str(h).replace("'", "").replace('"', '').strip()
            sz = normalize_size(h_clean)
            if sz:
                size_cols.append((col_idx, sz))

        section_df = df.iloc[max(0, h_idx - 5):h_idx]
        model_cell = ""
        for r in range(section_df.shape[0]):
            for c in range(section_df.shape[1]):
                val = str(section_df.iloc[r, c]).strip()
                if "model#:" in val.lower() or "model" in val.lower():
                    model_cell = val
                    break
            if model_cell:
                break

        model_name = ""
        if model_cell:
            model_match = re.search(r'Model#:\s*([A-Za-z0-9-]+)', model_cell)
            if model_match:
                model_name = model_match.group(1)
            else:
                model_name = model_cell

        for r_idx in range(h_idx + 1, next_h_idx):
            row = df.iloc[r_idx]
            po_val = str(row.iloc[po_idx]).strip() if po_idx is not None else ""
            if not po_val or po_val == "nan" or "total" in po_val.lower() or "grand" in po_val.lower():
                continue

            mat_val = str(row.iloc[mat_idx]).strip() if mat_idx is not None else ""
            desc_val = str(row.iloc[desc_idx]).strip() if desc_idx is not None else ""
            planning_val = str(row.iloc[planning_idx]).strip() if planning_idx is not None else ""

            etd_val = row.iloc[etd_idx] if etd_idx is not None else ""
            delivery_date = parse_excel_date(etd_val)

            row_model = model_name if model_name else planning_val

            size_qtys: dict[str, float] = {}
            for col_idx, sz_name in size_cols:
                if sz_name:
                    qty_val = row.iloc[col_idx]
                    try:
                        qty = float(qty_val)
                        if qty > 0:
                            size_qtys[sz_name] = qty
                    except (ValueError, TypeError):
                        pass

            if size_qtys:
                records.append(OrderRecord(
                    PO=po_val,
                    Date=delivery_date,
                    Model=row_model,
                    Material=mat_val,
                    ProductCode=mat_val,
                    Description=desc_val,
                    Price=0.0,
                    DeliveryDate=delivery_date,
                    CustomerCode=customer_code,
                    Gender="",
                    Sizes=size_qtys,
                ))

    return records


@register_parser(brand="NB", extensions=[".pdf"], customer_codes=["0473"])
def parse_pdf_nb_diamond(file_bytes: bytes, filename: str, customer_code: str) -> list[OrderRecord]:
    _logger.info(f"Parsing Diamond PDF: {filename} (Customer: {customer_code})")
    records: list[OrderRecord] = []

    import pdfplumber
    pdf_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pdf_text += page.extract_text() + "\n"

    line_match = re.search(
        r'\d+\.\s+(\S+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{4}/\d{2}/\d{2})\s+Allow\s+[\d.]+\s+\w+\s+\w+\s+\w+\s+(\d{4}/\d{2}/\d{2})\s+(\S+)',
        pdf_text
    )

    po = os.path.splitext(os.path.basename(filename))[0]
    order_date = ""
    delivery_date = ""
    model = ""

    if line_match:
        po = line_match.group(1)
        order_date = line_match.group(3).replace("/", "-") + " 00:00:00"
        delivery_date = line_match.group(4).replace("/", "-") + " 00:00:00"
        model = line_match.group(5)
        model = re.sub(r'\(S\d+.*', '', model)
    else:
        po_match = re.search(r'\b(N\d{5}-\d{2})\b', pdf_text)
        if po_match:
            po = po_match.group(1)
        date_matches = re.findall(r'\b\d{4}/\d{2}/\d{2}\b', pdf_text)
        if len(date_matches) >= 2:
            order_date = date_matches[0].replace("/", "-") + " 00:00:00"
            delivery_date = date_matches[-1].replace("/", "-") + " 00:00:00"
        style_match = re.search(r'StyleNo\s+.*?StyleNo.*?\n.*?\s+([A-Za-z0-9()]+)', pdf_text)
        if style_match:
            model = style_match.group(1)

    if not model:
        m = re.search(r'StyleNo\s+BarcodeNo.*?Price.*?\n.*?\s+([A-Za-z0-9()+-]+)', pdf_text)
        if m:
            model = m.group(1)

    price_match = re.search(r'USD\s+([\d.]+)', pdf_text)
    price = float(price_match.group(1)) if price_match else 0.0

    lines = pdf_text.split("\n")
    desc_lines: list[str] = []
    capture = False
    for line in lines:
        line_s = line.strip()
        if "PONo" in line_s and "ShippingDate" in line_s:
            capture = True
            continue
        if capture:
            if line_s.startswith("1."):
                break
            desc_lines.append(line_s)
    desc = " ".join([l for l in desc_lines if l and l != "●"])

    size_qtys: dict[str, float] = {}
    found_size_header = False
    for line in lines:
        if "Size" in line and "Qty" in line:
            found_size_header = True
            continue
        if found_size_header:
            tokens = line.strip().split()
            if len(tokens) >= 2 and len(tokens) % 2 == 0:
                is_grid_line = True
                pairs: list[tuple[str, float]] = []
                for i in range(0, len(tokens), 2):
                    sz = normalize_size(tokens[i])
                    try:
                        qty = float(tokens[i + 1])
                        if sz and qty >= 0:
                            pairs.append((sz, qty))
                    except ValueError:
                        is_grid_line = False
                        break
                if is_grid_line:
                    for sz, qty in pairs:
                        if qty > 0:
                            size_qtys[sz] = qty
            else:
                if len(tokens) > 0 and ("Manager" in line or "Approver" in line or "null" in line):
                    break

    if size_qtys:
        records.append(OrderRecord(
            PO=po,
            Date=order_date,
            Model=model,
            Material=model,
            ProductCode=model,
            Description=desc,
            Price=price,
            DeliveryDate=delivery_date,
            CustomerCode=customer_code,
            Gender="",
            Sizes=size_qtys,
        ))

    return records
