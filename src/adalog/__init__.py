"""adalog — self-contained multimodal data-recording platform.

This package is organized in enforced layers (see importlinter.ini):

- ``adalog.core``       goofi-free recording spine: clock, envelope, manifest, recorder, reader
- ``adalog.schema``     goofi-free declarative Field/config system
- ``adalog.adapters``   device-adapter SDK (base, supervisor, registry, templates)
- ``adalog.store``      BlobStore/Index interface + local backend
- ``adalog.bridge_codec`` vendored GOOF wire codec (goofi-free)
- ``adalog.convert``    legacy v0 -> v1 session converter
- ``adalog.sense``      the standalone recorder application (bridge + devices + CLI)
"""

__version__ = "1.0.0a0"
