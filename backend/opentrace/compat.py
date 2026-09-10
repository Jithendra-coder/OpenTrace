"""Compatibility utilities for Python < 3.11."""
from __future__ import annotations

import enum

# Ensure StrEnum is available on enum module for Python 3.10
if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        """Fallback StrEnum implementation for Python < 3.11."""
        def __str__(self) -> str:
            return str(self.value)

    enum.StrEnum = StrEnum

import sys
import datetime

# Ensure datetime.UTC is available on datetime module for Python 3.10
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc  # type: ignore[attr-defined]


# Ensure backward-compatibility aliases for legacy pickle models and modules
try:
    import opentrace
    sys.modules.setdefault("specimpact", opentrace)
    sys.modules.setdefault("changemesh", opentrace)
    import opentrace.ml
    sys.modules.setdefault("specimpact.ml", opentrace.ml)
    sys.modules.setdefault("changemesh.ml", opentrace.ml)
    import opentrace.ml.features
    sys.modules.setdefault("specimpact.ml.features", opentrace.ml.features)
    sys.modules.setdefault("changemesh.ml.features", opentrace.ml.features)
except Exception:
    pass

__all__ = ["StrEnum"]
