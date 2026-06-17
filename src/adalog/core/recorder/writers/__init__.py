"""StreamWriter implementations. Importing this package registers all built-in encodings."""
from .base import WRITER_REGISTRY, StreamWriter, get_writer, register_writer  # noqa: F401
from . import arrow_chunk  # noqa: F401  (registers arrow_ipc_stream)
from . import jsonl  # noqa: F401        (registers jsonl)
from . import wav  # noqa: F401          (registers wav)
from . import csv_ts  # noqa: F401       (registers csv_ts)
from . import png  # noqa: F401          (registers png)
from . import pentrace  # noqa: F401     (registers pentrace)

__all__ = ["WRITER_REGISTRY", "StreamWriter", "get_writer", "register_writer"]
