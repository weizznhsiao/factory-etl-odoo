"""
Fixed-coordinate parser for the '0325C-1' order format.

Strategy: RPA-style absolute-position extraction using pandas iloc.
No fuzzy matching or brand detection is used. Every cell is addressed
by its exact (row, column) index in a specific, named sheet.

Sheet layout
============
Sheet1          — header block (PO, date, price, delivery date)
LOT# Detail     — line detail (material, description, product code,
                   model, gender/logo, sizes & quantities)

LOT# Detail column layout (0-indexed)
--------------------------------------
Col 0  Code / Material code        (e.g. LJ-B1150B-VEPM5-NODYE)
Col 1  Description of goods        (long LOGO / colour description)
Col 2  RP LOT#
Col 3  PPW
Col 4  Product Code                (e.g. GC1906CT-GEI)
Col 5  Model Name                  (e.g. GC1906V1)
Col 6  Gender                      (Unisex / Kids(M) / Kids(W))
Col 7  Total
Col 8+ Size quantity columns       (headers: 3.5#, 4.0#, … with '#' suffix)

Multiple data rows (from iloc[4] downward) exist for the same order;
sizes are aggregated across all rows into a single OrderRecord.
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import pandas as pd

from ..models import OrderRecord
from ..registry import register_parser
from ..utils import parse_excel_date

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Coordinate constants — Sheet1
# ---------------------------------------------------------------------------
_S1_PO_ROW,       _S1_PO_COL       = 3,  14   # iloc[3, 14]  → P.O.NO. / 客戶單號 (BLK934/25)
_S1_DATE_ROW,     _S1_DATE_COL     = 5,  14   # iloc[5, 14]  → DATE
_S1_PRICE_ROW,    _S1_PRICE_COL    = 11,  8   # iloc[11, 8]  → U/P
_S1_DELIVERY_ROW, _S1_DELIVERY_COL = 11, 11   # iloc[11, 11] → RTD


# ---------------------------------------------------------------------------
# Coordinate constants — LOT# Detail sheet (first data row)
# ---------------------------------------------------------------------------
_LD_DATA_START_ROW    = 4   # iloc[4] — first data row (Excel row 5)
_LD_MATERIAL_COL      = 0   # Code / fabric code
_LD_DESC_COL          = 1   # Description of goods (LOGO text)
_LD_PRODUCTCODE_COL   = 4   # Product Code
_LD_MODEL_COL         = 5   # Model Name
_LD_GENDER_COL        = 6   # Gender (used only for 升降碼 logic)

_LD_SIZE_HEADER_ROW   = 2   # iloc[2]   — size label row
_LD_SIZE_START_COL    = 8   # sizes begin at 0-indexed column 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cell(df: pd.DataFrame, row: int, col: int) -> str:
    """Safely read a single cell; return empty string on NaN / IndexError."""
    try:
        value = df.iloc[row, col]
        if pd.isna(value):
            return ""
        return str(value).strip()
    except (IndexError, TypeError):
        return ""


def _normalise_size_label(raw: str) -> Optional[str]:
    """
    Convert a size header cell into a normalised string key.

    Handles:
    * Trailing '#'  →  strip it          ("3.5#" → "3.5")
    * Integer-like  →  add ".0"          ("4"    → "4.0")
    * Numeric float →  keep as-is        ("4.5"  → "4.5")
    * Non-numeric   →  return as-is      ("S"    → "S")
    * Empty / NaN   →  return None
    """
    cleaned = raw.strip().rstrip("#").strip()
    if not cleaned or cleaned.lower() in ("nan", "total", "合計", "mold size run"):
        return None
    try:
        return f"{float(cleaned):.1f}"
    except ValueError:
        return cleaned  # non-numeric label (e.g. "S", "M")


def _build_size_label_map(df: pd.DataFrame) -> dict[int, str]:
    """
    Return a mapping {col_index: normalised_size_label} for all valid size
    columns in the header row (iloc[2], starting at col _LD_SIZE_START_COL).
    """
    label_map: dict[int, str] = {}
    n_cols = df.shape[1]
    for col_idx in range(_LD_SIZE_START_COL, n_cols):
        raw = _cell(df, _LD_SIZE_HEADER_ROW, col_idx)
        label = _normalise_size_label(raw)
        if label:
            label_map[col_idx] = label
    return label_map


def _read_all_sizes(
    df: pd.DataFrame,
    label_map: dict[int, str],
) -> dict[str, float]:
    """
    Aggregate size quantities from **all data rows** (iloc[4] onward).

    A row is considered valid when the value in _LD_MATERIAL_COL is not
    empty / NaN.  Quantities are summed across rows sharing the same
    normalised size label.
    """
    sizes: dict[str, float] = {}
    n_rows = df.shape[0]

    for row_idx in range(_LD_DATA_START_ROW, n_rows):
        # Stop at the first completely empty row
        material_val = _cell(df, row_idx, _LD_MATERIAL_COL)
        gender_val   = _cell(df, row_idx, _LD_GENDER_COL)
        if not material_val and not gender_val:
            break

        for col_idx, size_label in label_map.items():
            qty_raw = df.iloc[row_idx, col_idx]
            try:
                qty = float(qty_raw)
            except (ValueError, TypeError):
                qty = 0.0
            if qty > 0:
                sizes[size_label] = sizes.get(size_label, 0.0) + qty

    return sizes


def _has_jrs_gender(df: pd.DataFrame) -> bool:
    """
    Scan all data rows for a Gender value containing 'Kids' or 'JRS'.
    Returns True if found in any row.
    """
    n_rows = df.shape[0]
    for row_idx in range(_LD_DATA_START_ROW, n_rows):
        gender = _cell(df, row_idx, _LD_GENDER_COL)
        if not gender:
            continue
        if "Kids" in gender or "JRS" in gender:
            return True
    return False


# ---------------------------------------------------------------------------
# Parser registration
# ---------------------------------------------------------------------------

@register_parser(
    brand="0325C",
    extensions=[".xlsx", ".xls"],
    customer_codes=["0325c"],
)
def parse_fixed_0325c(
    file_bytes: bytes,
    filename: str,
    customer_code: str,
) -> list[OrderRecord]:
    """
    Parse a '0325C-1' format Excel order using absolute iloc coordinates.

    * Reads header block from Sheet1.
    * Reads first data row (iloc[4]) for material / description / product /
      model fields from the 'LOT# Detail' sheet.
    * Aggregates size quantities across **all** data rows in 'LOT# Detail'.
    * Returns a list containing exactly one OrderRecord on success.
    """
    _logger.info(f"[0325C] Parsing fixed-format file: {filename}")
    records: list[OrderRecord] = []

    f = io.BytesIO(file_bytes)

    # ------------------------------------------------------------------
    # 1. Read Sheet1 — header information
    # ------------------------------------------------------------------
    try:
        df_sheet1 = pd.read_excel(f, sheet_name="Sheet1", header=None, dtype=str)
    except Exception as exc:
        _logger.error(f"[0325C] Cannot read 'Sheet1' from '{filename}': {exc}")
        return records

    po: str           = _cell(df_sheet1, _S1_PO_ROW,       _S1_PO_COL)
    date_raw: str     = _cell(df_sheet1, _S1_DATE_ROW,     _S1_DATE_COL)
    price_raw: str    = _cell(df_sheet1, _S1_PRICE_ROW,    _S1_PRICE_COL)
    delivery_raw: str = _cell(df_sheet1, _S1_DELIVERY_ROW, _S1_DELIVERY_COL)

    order_date: str    = parse_excel_date(date_raw)
    delivery_date: str = parse_excel_date(delivery_raw)

    try:
        price: float = float(price_raw)
    except (ValueError, TypeError):
        price = 0.0
        _logger.warning(
            f"[0325C] Cannot parse price '{price_raw}' in '{filename}'; defaulting to 0.0"
        )

    if not po:
        _logger.warning(f"[0325C] PO is empty in '{filename}'; skipping file.")
        return records

    # ------------------------------------------------------------------
    # 2. Read LOT# Detail sheet
    # ------------------------------------------------------------------
    f.seek(0)
    try:
        df_detail = pd.read_excel(f, sheet_name="LOT# Detail", header=None, dtype=str)
    except Exception as exc:
        _logger.error(f"[0325C] Cannot read 'LOT# Detail' from '{filename}': {exc}")
        return records

    # -- 2a. Static fields from the FIRST data row (iloc[4]) --
    material:     str = _cell(df_detail, _LD_DATA_START_ROW, _LD_MATERIAL_COL)
    description:  str = _cell(df_detail, _LD_DATA_START_ROW, _LD_DESC_COL)
    product_code: str = _cell(df_detail, _LD_DATA_START_ROW, _LD_PRODUCTCODE_COL)
    model:        str = _cell(df_detail, _LD_DATA_START_ROW, _LD_MODEL_COL)

    # Gender string — kept for 升降碼 logic in mapper;
    # scan all rows so Kids in any row triggers JRS tier.
    # We store a sentinel that tells the mapper "JRS applies" when relevant.
    jrs_flag = _has_jrs_gender(df_detail)
    gender: str = "Kids(M)" if jrs_flag else _cell(df_detail, _LD_DATA_START_ROW, _LD_GENDER_COL)

    # -- 2b. Build size label map from header row, then aggregate quantities --
    label_map = _build_size_label_map(df_detail)
    sizes: dict[str, float] = _read_all_sizes(df_detail, label_map)

    if not sizes:
        _logger.warning(f"[0325C] No size/qty pairs found in '{filename}'.")

    # ------------------------------------------------------------------
    # 3. Assemble OrderRecord
    #    Field semantics (matches mapper expectations):
    #      Material    → LOT# Detail col 0  (fabric/material code)
    #      Description → LOT# Detail col 1  (long LOGO/colour description)
    #      Gender      → used only for 升降碼 logic
    # ------------------------------------------------------------------
    record = OrderRecord(
        PO=po,
        Date=order_date,
        Model=model,
        Material=material,
        ProductCode=product_code,
        Description=description,
        Price=price,
        DeliveryDate=delivery_date,
        CustomerCode="0325C",
        Gender=gender,
        Sizes=sizes,
    )

    records.append(record)
    _logger.info(
        f"[0325C] Parsed 1 record — PO={po!r}, sizes={list(sizes.keys())}"
    )
    return records
