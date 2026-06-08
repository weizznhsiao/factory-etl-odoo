"""
Unified data models for the Factory Order ETL system.
"""

from __future__ import annotations
import sys

if sys.version_info >= (3, 8):
    from typing import TypedDict
else:
    # Python 3.7 fallback
    TypedDict = dict


class OrderRecord(TypedDict):
    PO: str
    Date: str
    Model: str
    Material: str
    ProductCode: str
    Description: str
    Price: float
    DeliveryDate: str
    CustomerCode: str
    Gender: str
    Sizes: dict[str, float]


class VerticalRecord(TypedDict):
    PO: str
    Date: str
    Model: str
    Material: str
    ProductCode: str
    Description: str
    Price: float
    DeliveryDate: str
    CustomerCode: str
    Gender: str
    Size: str
    Qty: float
