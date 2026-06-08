"""
Parser Registry — dynamic parser dispatch via decorator registration.
Adapted for Odoo in-memory processing.
"""

from __future__ import annotations
from typing import Callable, Optional, List
from .models import OrderRecord
import logging

_logger = logging.getLogger(__name__)


# Type alias for parser functions: (file_content_bytes, filename, customer_code) -> List[OrderRecord]
ParserFunc = Callable[[bytes, str, str], List[OrderRecord]]


class _ParserEntry:
    __slots__ = ("func", "brand", "extensions", "customer_codes", "sheet_predicate")

    def __init__(
        self,
        func: ParserFunc,
        brand: str,
        extensions: list[str],
        customer_codes: Optional[list[str]] = None,
        sheet_predicate: Optional[Callable[[bytes, list[str]], bool]] = None,
    ):
        self.func = func
        self.brand = brand.lower()
        self.extensions = [ext.lower() for ext in extensions]
        self.customer_codes = [c.lower() for c in customer_codes] if customer_codes else None
        self.sheet_predicate = sheet_predicate


_registry: list[_ParserEntry] = []


def register_parser(
    brand: str,
    extensions: list[str],
    customer_codes: Optional[list[str]] = None,
    sheet_predicate: Optional[Callable[[bytes, list[str]], bool]] = None,
) -> Callable[[ParserFunc], ParserFunc]:
    def decorator(func: ParserFunc) -> ParserFunc:
        entry = _ParserEntry(
            func=func,
            brand=brand,
            extensions=extensions,
            customer_codes=customer_codes,
            sheet_predicate=sheet_predicate,
        )
        _registry.append(entry)
        return func
    return decorator


def dispatch(
    brand: str,
    filename: str,
    customer_code: str,
    file_bytes: Optional[bytes] = None,
    sheet_names: Optional[list[str]] = None,
) -> Optional[ParserFunc]:
    import os
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    brand_lower = brand.lower()
    code_lower = customer_code.lower()

    for entry in _registry:
        if entry.brand == brand_lower and ext in entry.extensions:
            if entry.customer_codes and code_lower in entry.customer_codes:
                return entry.func

    if sheet_names is not None and file_bytes is not None:
        for entry in _registry:
            if entry.brand == brand_lower and ext in entry.extensions:
                if entry.sheet_predicate and entry.sheet_predicate(file_bytes, sheet_names):
                    return entry.func

    for entry in _registry:
        if entry.brand == brand_lower and ext in entry.extensions:
            if entry.customer_codes is None and entry.sheet_predicate is None:
                return entry.func

    return None


def _get_xls_sheet_names(file_bytes: bytes) -> Optional[list[str]]:
    """Helper to get sheet names from an XLS file."""
    try:
        import io
        import pandas as pd
        xl = pd.ExcelFile(io.BytesIO(file_bytes), engine="xlrd")
        return xl.sheet_names
    except Exception:
        return None


def try_all_parsers(
    filename: str,
    file_bytes: bytes,
    customer_code: str = "",
) -> Optional[List[OrderRecord]]:
    """
    Tries all registered parsers that match the file extension.
    Returns the first successful result, or None if no parser succeeds.
    """
    import os
    _, ext = os.path.splitext(filename)
    ext = ext.lower()

    # Get sheet names for XLS files (used by some parsers)
    sheet_names = None
    if ext == ".xls":
        sheet_names = _get_xls_sheet_names(file_bytes)

    # Collect candidate parsers matching the extension
    candidates: list[_ParserEntry] = [e for e in _registry if ext in e.extensions]

    if not candidates:
        _logger.warning(f"No parsers registered for extension '{ext}' (file: {filename})")
        return None

    # Try each parser; return first successful result
    for entry in candidates:
        try:
            records = entry.func(file_bytes, filename, customer_code)
            if records:
                _logger.info(f"Parser '{entry.brand}' successfully parsed {len(records)} records from '{filename}'")
                return records
        except Exception as e:
            _logger.debug(f"Parser '{entry.brand}' failed for '{filename}': {e}")
            continue

    _logger.warning(f"All parsers failed for file: {filename}")
    return None
