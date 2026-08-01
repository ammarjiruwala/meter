"""Deprecated entrypoint — kept so `uvicorn main:app` keeps working.

The treasury and Prava routes that used to live here are now part of the proxy app
(`proxy/app.py`), so the whole backend is one process on one port:

    uvicorn proxy.app:app --port 8080

This module re-exports that same app object. Nothing is lost by using it, but prefer
the line above; this file goes away once nobody's notes point at it.

Owner: Shivam (Payments & Agent).
"""

from proxy.app import app

__all__ = ["app"]
