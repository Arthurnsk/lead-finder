"""TLS trust for .gov.ru: they are signed by the Russian national CA, absent from certifi."""

from __future__ import annotations

import glob
import ssl
from functools import lru_cache

import certifi

RU_CERT_GLOB = "/usr/local/share/ca-certificates/russian*.crt"


@lru_cache(maxsize=1)
def gov_ssl_context() -> ssl.SSLContext:
    """Normal verification plus the Russian root/intermediate certificates shipped in the image."""
    ctx = ssl.create_default_context(cafile=certifi.where())
    for path in sorted(glob.glob(RU_CERT_GLOB)):
        try:
            ctx.load_verify_locations(path)
        except ssl.SSLError:
            continue
    return ctx
