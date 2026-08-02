"""Judge sessions — the "Try it yourself" flow described in PITCH.md.

A judge gets their own tenant (`projects` + `meter_keys` rows), so every existing code
path — authentication, attribution, ceilings, the breaker, the Treasurer — treats them
like any other project without modification. This package owns only the parts that are
specific to *being a judge session*: provisioning, expiry, call caps, and the in-process
vault holding the credentials they paste.

Owner: Ammar.
"""

from .sessions import (
    PROJECT_PREFIX,
    alert_target,
    Session,
    create,
    forget_secrets,
    purge_expired,
    put_secrets,
    resolve,
    secrets_for,
)

__all__ = [
    "PROJECT_PREFIX",
    "alert_target",
    "Session",
    "create",
    "forget_secrets",
    "purge_expired",
    "put_secrets",
    "resolve",
    "secrets_for",
]
