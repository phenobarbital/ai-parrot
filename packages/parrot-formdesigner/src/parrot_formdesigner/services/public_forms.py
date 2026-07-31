"""Helper for computing auth-exempt URL patterns for public forms (FEAT-241)."""

__all__ = ["public_form_paths"]


def public_form_paths(form_uid: str, base_path: str = "/api/v1") -> list[str]:
    """Return the auth-exempt glob patterns for a public form.

    These five patterns cover all read and submission URLs that should be
    reachable without authentication when a form has ``is_public=True``.

    Used by both the lifecycle toggle and the exclude-provider registration
    so that both callers always register/unregister the same set of paths.

    Args:
        form_uid: The form's immutable UUID identity (FEAT-389). NOT
            ``form_id`` — routes are ``{form_uid}``-based (TASK-1976), so
            exclusion patterns built from the slug would not match the
            real URLs.
        base_path: URL prefix used when the form API was mounted (must match
                   the ``base_path`` passed to ``setup_form_api``).
                   Trailing slashes are stripped automatically.

    Returns:
        List of five URL patterns (fnmatch globs):

          - ``{base_path}/forms/{form_uid}``            — GET form object
          - ``{base_path}/forms/{form_uid}/schema``     — GET JSON schema
          - ``{base_path}/forms/{form_uid}/render/*``   — GET rendered formats (glob)
          - ``{base_path}/forms/{form_uid}/data``       — POST submit results
          - ``{base_path}/forms/{form_uid}/validate``   — POST pre-submit validation
    """
    bp = base_path.rstrip("/")
    base = f"{bp}/forms/{form_uid}"
    return [
        base,
        f"{base}/schema",
        f"{base}/render/*",
        f"{base}/data",
        f"{base}/validate",
    ]
