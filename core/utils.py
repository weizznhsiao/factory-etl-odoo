"""
Shared utility functions for the Factory Order ETL system.
"""

from __future__ import annotations
import re
from typing import Any, Optional, Sequence
import pandas as pd
import logging

_logger = logging.getLogger(__name__)


def normalize_size(sz_str: Any) -> Optional[str]:
    sz_str = str(sz_str).strip().lower().replace('#', '')
    if not sz_str or sz_str == 'nan':
        return None
    try:
        if sz_str.isdigit() and len(sz_str) == 3:
            val = float(sz_str) / 10.0
            return f"{val:.1f}"

        match = re.search(r'(\d+(?:\.\d+)?)', sz_str)
        if match:
            val = float(match.group(1))
            if val < 20:
                val = round(val * 2) / 2
                return f"{val:.1f}"
    except (ValueError, TypeError):
        pass
    return None


def parse_excel_date(val: Any) -> str:
    if pd.isna(val) or str(val).strip() == "" or str(val).lower() == "nan":
        return ""
    try:
        num = float(val)
        dt = pd.to_datetime(num, unit='D', origin='1899-12-30')
        return dt.strftime('%Y-%m-%d 00:00:00')
    except (ValueError, TypeError, OverflowError):
        try:
            dt = pd.to_datetime(val)
            return dt.strftime('%Y-%m-%d 00:00:00')
        except (ValueError, TypeError):
            return str(val).strip()


def find_col_idx(row: Sequence[Any], names: list[str]) -> Optional[int]:
    for idx, cell in enumerate(row):
        cell_str = str(cell).strip().lower()
        for name in names:
            if name.lower() in cell_str:
                return idx
    return None


def find_val_near_label(df: pd.DataFrame, labels: list[str]) -> Any:
    for r_idx in range(df.shape[0]):
        for c_idx in range(df.shape[1]):
            cell_val = str(df.iloc[r_idx, c_idx]).strip()
            for label in labels:
                if label.lower() in cell_val.lower():
                    for offset in range(1, 5):
                        if c_idx + offset < df.shape[1]:
                            val = df.iloc[r_idx, c_idx + offset]
                            if pd.notna(val) and str(val).strip() != "":
                                return val
    return None
