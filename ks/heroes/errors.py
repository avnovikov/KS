"""Shared exceptions for heroes / gear automation."""

from __future__ import annotations


class DetailOpenError(RuntimeError):
    """Detail screen/modal is open but scrape produced no usable record.

    Collectors must close the detail before continuing the grid walk.
    """
