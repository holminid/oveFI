#!/usr/bin/env python3
"""analysis.io.loaders

Small helper to load CSV files into pandas DataFrames and normalize headers
by stripping surrounding whitespace from column names.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd


def load_csv(path: str, *, encoding: Optional[str] = None, **kwargs) -> pd.DataFrame:
    """Load a CSV file into a pandas DataFrame and strip header whitespace.

    Parameters
    - path: path to CSV file
    - encoding: optional encoding passed to pandas.read_csv
    - kwargs: additional keyword args forwarded to pandas.read_csv

    Returns
    - pandas.DataFrame with stripped column names

    Raises
    - FileNotFoundError if path does not exist
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(path, encoding=encoding, **kwargs)

    # Normalize header names by stripping whitespace
    if df.columns is not None:
        df.columns = [c.strip() if isinstance(c, str) else c for c in df.columns]

    return df
