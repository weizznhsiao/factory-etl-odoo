"""
Unified field mapper — single source of truth for mapping OrderRecords
to ERP (TipTop) template columns.

Design principles
=================
* **No fuzzy matching.** Every column name written here is the exact,
  byte-for-byte string that appears in the TipTop export template,
  including unusual spacing and typos (e.g. "Shoe Modek (tc_oea20 )").
* `_assign_exact` performs a strict ``col_name in headers`` membership
  check; if the column is absent from the template the value is silently
  skipped, which means the mapper is forward-compatible with future
  template revisions.
* The 升降碼 (size-code) logic encodes the business rule for Kids/JRS
  product lines without any string searching against the template.
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import OrderRecord

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core primitive
# ---------------------------------------------------------------------------

def _assign_exact(
    row_dict: dict[str, object],
    headers: list[str],
    col_name: str,
    value: object,
) -> None:
    """
    Write *value* into *row_dict* under key *col_name* **only** if
    *col_name* is present in *headers* (100 % exact match, no fuzzy logic).

    Parameters
    ----------
    row_dict : dict
        The output row being built; keys are column names.
    headers : list[str]
        All column names that exist in the target template.
    col_name : str
        The exact column name to target — must be character-perfect.
    value : object
        The value to write.
    """
    if col_name in headers:
        row_dict[col_name] = value
    else:
        _logger.debug(
            "_assign_exact: column %r not found in template headers; skipped.", col_name
        )


# ---------------------------------------------------------------------------
# Size-column index builder
# ---------------------------------------------------------------------------

def build_size_cols_map(headers: list[str]) -> dict[str, str]:
    """
    Build a mapping from normalised size string (e.g. ``"36.0"``) to the
    verbatim column name in the template (e.g. ``"36"`` or ``"36.0"``).

    Only columns whose headers can be interpreted as a floating-point
    number are included.  Non-numeric headers (text field names) are
    intentionally ignored.
    """
    size_cols_map: dict[str, str] = {}
    for col in headers:
        col_str = str(col).strip()
        try:
            val = float(col_str)
            normalised = f"{val:.1f}"
            size_cols_map[normalised] = col
        except ValueError:
            pass
    return size_cols_map


# ---------------------------------------------------------------------------
# Horizontal (one row per OrderRecord)
# ---------------------------------------------------------------------------

def build_horizontal_row(
    record: OrderRecord,
    headers: list[str],
    size_cols_map: dict[str, str],
) -> dict[str, object]:
    """
    Map a single *record* onto a flat dictionary whose keys are every
    column name in *headers*.  Unrecognised columns retain an empty string.

    Parameters
    ----------
    record : OrderRecord
        The parsed order data.
    headers : list[str]
        Ordered list of column names from the TipTop import template.
    size_cols_map : dict[str, str]
        Pre-built mapping from normalised size string to template column name
        (use :func:`build_size_cols_map`).

    Returns
    -------
    dict[str, object]
        A single row ready to be appended to the output DataFrame.
    """
    row_dict: dict[str, object] = {col: "" for col in headers}

    # ------------------------------------------------------------------
    # Header fields — exact column names (including spaces/typos)
    # ------------------------------------------------------------------

    # 客戶PO 和 客戶單號 同源 iloc[3,14]
    _assign_exact(row_dict, headers, "客戶PO(tc_oea26)",           record.get("PO", ""))
    _assign_exact(row_dict, headers, "客戶單號(tc_oea05)",          record.get("PO", ""))

    # Order date
    _assign_exact(row_dict, headers, "訂單日期(tc_oea02)",          record.get("Date", ""))

    # Customer code — always "0325C" for this format
    _assign_exact(row_dict, headers, "客戶編號(tc_oea03)",          record.get("CustomerCode", ""))

    # 升降碼 — Kids / JRS → "3:JRS", all others → "1:MS"
    gender_info: str = str(record.get("Gender", ""))
    jrs_code = "3:JRS" if ("Kids" in gender_info or "JRS" in gender_info) else "1:MS"
    _assign_exact(row_dict, headers, "升降碼(tc_oea12)",            jrs_code)

    # 布料 = fabric/material code (LOT# Detail col 0)
    # LOGO = long colour/logo description (LOT# Detail col 1)
    _assign_exact(row_dict, headers, "布料(tc_oea13)",              record.get("Material", ""))
    _assign_exact(row_dict, headers, "LOGO(tc_oea14)",              record.get("Description", ""))

    # Fields with intentional typos / unusual spacing — copied verbatim
    _assign_exact(row_dict, headers, "Shoe Modek (tc_oea20 )",     record.get("Model", ""))
    _assign_exact(row_dict, headers, "Material No    (tc_oea21)",   record.get("Material", ""))

    # Line-level fields
    _assign_exact(row_dict, headers, "產品編號(tc_oeb04)",          record.get("ProductCode", ""))
    _assign_exact(row_dict, headers, "未稅單價(tc_oeb08)",          record.get("Price", ""))
    _assign_exact(row_dict, headers, "約定交貨日(tc_oeb10)",        record.get("DeliveryDate", ""))

    # ------------------------------------------------------------------
    # Size quantities — matched via normalised float key
    # ------------------------------------------------------------------
    for sz_name, qty in record["Sizes"].items():
        if sz_name in size_cols_map:
            original_col = size_cols_map[sz_name]
            row_dict[original_col] = qty
        else:
            _logger.warning(
                "Size %r not found in template columns (qty=%s, PO=%s).",
                sz_name, qty, record.get("PO"),
            )

    return row_dict


# ---------------------------------------------------------------------------
# Vertical (one row per size per OrderRecord)
# ---------------------------------------------------------------------------

def build_vertical_rows(
    record: OrderRecord,
    headers: list[str],
) -> list[dict[str, object]]:
    """
    Expand a single *record* into multiple flat rows — one per size entry
    with quantity > 0 — suitable for a vertical TipTop import template.

    Parameters
    ----------
    record : OrderRecord
        The parsed order data.
    headers : list[str]
        Ordered list of column names from the vertical TipTop template.

    Returns
    -------
    list[dict[str, object]]
        One dictionary per (size, qty) pair.
    """
    rows: list[dict[str, object]] = []

    for sz_name, qty in record["Sizes"].items():
        if qty <= 0:
            continue

        row_dict: dict[str, object] = {col: "" for col in headers}

        # Header fields (identical to horizontal)
        _assign_exact(row_dict, headers, "客戶PO(tc_oea26)",        record.get("PO", ""))
        _assign_exact(row_dict, headers, "客戶單號(tc_oea05)",       record.get("PO", ""))
        _assign_exact(row_dict, headers, "訂單日期(tc_oea02)",       record.get("Date", ""))
        _assign_exact(row_dict, headers, "客戶編號(tc_oea03)",       record.get("CustomerCode", ""))

        gender_info = str(record.get("Gender", ""))
        jrs_code = "3:JRS" if ("Kids" in gender_info or "JRS" in gender_info) else "1:MS"
        _assign_exact(row_dict, headers, "升降碼(tc_oea12)",         jrs_code)

        _assign_exact(row_dict, headers, "布料(tc_oea13)",           record.get("Material", ""))
        _assign_exact(row_dict, headers, "LOGO(tc_oea14)",           record.get("Description", ""))
        _assign_exact(row_dict, headers, "Shoe Modek (tc_oea20 )",  record.get("Model", ""))
        _assign_exact(row_dict, headers, "Material No    (tc_oea21)", record.get("Material", ""))
        _assign_exact(row_dict, headers, "產品編號(tc_oeb04)",       record.get("ProductCode", ""))
        _assign_exact(row_dict, headers, "未稅單價(tc_oeb08)",       record.get("Price", ""))
        _assign_exact(row_dict, headers, "約定交貨日(tc_oeb10)",     record.get("DeliveryDate", ""))

        # Vertical-specific: size name and quantity go into dedicated columns
        _assign_exact(row_dict, headers, "尺寸",   sz_name)
        _assign_exact(row_dict, headers, "計價數量", qty)

        rows.append(row_dict)

    return rows