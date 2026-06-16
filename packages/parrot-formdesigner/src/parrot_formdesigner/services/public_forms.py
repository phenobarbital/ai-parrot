"""Helper for computing auth-exempt URL patterns for public forms (FEAT-241)."""

__all__ = ["public_form_paths"]


def public_form_paths(form_id: str, base_path: str = "/api/v1") -> list[str]:
    """Return the auth-exempt glob patterns for a public form.

    These five patterns cover all read and submission URLs that should be
    reachable without authentication when a form has ``is_public=True``.

    Used by both the lifecycle toggle (TASK-1582) and the exclude-provider
    (TASK-1583) so that both callers always register/unregister the same
    set of paths.

    Args:
        form_id: The form's unique identifier.
        base_path: URL prefix used when the form API was mounted (must match
                   the ``base_path`` passed to ``setup_form_api``).
                   Trailing slashes are stripped automatically.

    Returns:
        List of five URL patterns (fnmatch globs):

          - ``{base_path}/forms/{form_id}``            — GET form object
          - ``{base_path}/forms/{form_id}/schema``     — GET JSON schema
          - ``{base_path}/forms/{form_id}/render/*``   — GET rendered formats (glob)
          - ``{base_path}/forms/{form_id}/data``       — POST submit results
          - ``{base_path}/forms/{form_id}/validate``   — POST pre-submit validation
    """
    bp = base_path.rstrip("/")
    base = f"{bp}/forms/{form_id}"
    return [
        base,
        f"{base}/schema",
        f"{base}/render/*",
        f"{base}/data",
        f"{base}/validate",
    ]
