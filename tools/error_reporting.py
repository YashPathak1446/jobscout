"""
Error reporting to Sentry, hosted backend only (A9, R119).

Off unless `SENTRY_DSN` is set, so a checkout, the CLI and the test suite
send nothing and do not even import `sentry_sdk`. The hosted instance sets it
as a Fly secret (pilot plan A12).

What reaches Sentry is the smallest thing that still says what broke:

- `send_default_pii=False`: no IP, no user, no cookies from the integration.
- `include_local_variables=False`: no frame locals. A run's frames hold the
  key, the resume and the job descriptions.
- `max_request_body_size="never"`: no request body. The extract route's body
  is a resume and the key beside it.
- Logging below WARNING leaves no breadcrumb.
- `_scrub`, as `before_send`, replaces every held key (R117's registry) in
  every string of the event, and drops the request's headers and cookies.
  The same scrub runs on each breadcrumb as it is recorded, because a
  breadcrumb is sent with a later event, and by then the key that was held
  when it was written may have been released.

**The scrub knows only keys that are held** (`config.key_in_use`). The run
worker and the import both turn an exception into an event or text while the
key is held, and the extract route answers everything with a 4xx `from
None`, which Sentry does not report. A new path that lets an exception carry
a key out of `key_in_use` would reach Sentry unscrubbed.
"""

import logging
import os

DSN_ENV_VAR = "SENTRY_DSN"


def _scrub_value(value):
    """`value` with every string in it, at any depth, run through the scrubber."""
    from config import redact_keys

    if isinstance(value, str):
        return redact_keys(value)
    if isinstance(value, dict):
        return {_scrub_value(k): _scrub_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub_value(v) for v in value)
    return value


def _scrub(event, hint=None):
    """
    `before_send`: every string scrubbed, request headers and cookies dropped.

    Everything, not a list of fields: exception values, messages, breadcrumbs,
    tags, extra and contexts are all strings somewhere, and a list is R80's
    "count them" problem with a credential at stake. If this raises, Sentry
    drops the event rather than sending it unscrubbed.
    """
    event = _scrub_value(event)
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("headers", None)
        request.pop("cookies", None)
    return event


def _scrub_breadcrumb(crumb, hint=None):
    """`before_breadcrumb`: the same scrub, while the key is still held."""
    return _scrub_value(crumb)


def start_error_reporting() -> bool:
    """
    Start Sentry if `SENTRY_DSN` is set. Returns whether it started.

    With the variable set and `sentry_sdk` missing, this raises: a deploy that
    asked for error reporting and silently has none is the failure A5 made
    loud for the mode flag.
    """
    dsn = os.environ.get(DSN_ENV_VAR, "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError as exc:
        raise RuntimeError(
            f"{DSN_ENV_VAR} is set but sentry-sdk is not installed. "
            "Install requirements.txt, or unset it.") from exc

    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=_scrub,
        before_breadcrumb=_scrub_breadcrumb,
        integrations=[
            # Breadcrumbs from WARNING up; an event from ERROR up, the default.
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
    )
    return True
