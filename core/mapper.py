"""
Unified field mapper — single source of truth for mapping OrderRecords
to ERP template columns.
"""

from __future__ import annotations
from typing import Optional
from .models import OrderRecord
from .utils import find_col_idx
import logging

_logger = logging.getLogger(__name__)


def build_horizontal_row(
    record: OrderRecord,
    headers: list[str],
    size_cols_map: dict[str, str],
) -> dict[str, object]:
    row_dict: dict[str, object] = {col: "" for col in headers}

    row_dict["客戶PO(tc_oea26)"] = record["PO"]
    row_dict["客戶單號(tc_oea05)"] = record["PO"]
    row_dict["訂單日期(tc_oea02)"] = record["Date"]
    row_dict["客戶編號(tc_oea03)"] = record["CustomerCode"]
    row_dict["升降碼(tc_oea12)"] = "MS"
    row_dict["布料(tc_oea13)"] = record["Description"]
    row_dict["LOGO(tc_oea14)"] = record.get("Gender", "")

    _set_fuzzy(row_dict, headers, ["shoe modek", "shoe model"], record["Model"])
    _set_fuzzy(row_dict, headers, ["material no", "material_no"], record["Material"])
    _set_fuzzy(row_dict, headers, ["產品編號"], record["ProductCode"])
    _set_fuzzy(row_dict, headers, ["未稅單價"], record["Price"])
    _set_fuzzy(row_dict, headers, ["約定交貨日"], record["DeliveryDate"])

    for sz_name, qty in record["Sizes"].items():
        if sz_name in size_cols_map:
            original_col = size_cols_map[sz_name]
            row_dict[original_col] = qty
        else:
            _logger.warning(f"Size '{sz_name}' not found in template columns! Qty: {qty} for PO: {record['PO']}")

    return row_dict


def build_vertical_rows(
    record: OrderRecord,
    headers: list[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    for sz_name, qty in record["Sizes"].items():
        if qty <= 0:
            continue

        row_dict: dict[str, object] = {col: "" for col in headers}

        row_dict["客戶PO(tc_oea26)"] = record["PO"]
        row_dict["客戶單號(tc_oea05)"] = record["PO"]
        row_dict["訂單日期(tc_oea02)"] = record["Date"]
        row_dict["客戶編號(tc_oea03)"] = record["CustomerCode"]
        row_dict["升降碼(tc_oea12)"] = "MS"
        row_dict["布料(tc_oea13)"] = record["Description"]
        row_dict["LOGO(tc_oea14)"] = record.get("Gender", "")

        _set_fuzzy(row_dict, headers, ["shoe modek", "shoe model"], record["Model"])
        _set_fuzzy(row_dict, headers, ["material no", "material_no"], record["Material"])
        _set_fuzzy(row_dict, headers, ["產品編號"], record["ProductCode"])
        _set_fuzzy(row_dict, headers, ["未稅單價"], record["Price"])
        _set_fuzzy(row_dict, headers, ["約定交貨日"], record["DeliveryDate"])

        _set_fuzzy(row_dict, headers, ["尺寸"], sz_name)
        _set_fuzzy(row_dict, headers, ["計價數量"], qty)

        rows.append(row_dict)

    return rows


def build_size_cols_map(headers: list[str]) -> dict[str, str]:
    size_cols_map: dict[str, str] = {}
    for col in headers:
        col_str = str(col).strip()
        try:
            val = float(col_str)
            normalized = f"{val:.1f}"
            size_cols_map[normalized] = col
        except ValueError:
            pass
    return size_cols_map


def _set_fuzzy(
    row_dict: dict[str, object],
    headers: list[str],
    names: list[str],
    value: object,
) -> None:
    col_idx: Optional[int] = find_col_idx(headers, names)
    if col_idx is not None:
        row_dict[headers[col_idx]] = value
