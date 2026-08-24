"""Local conftest for `tests/integration/` — re-exports shared fixtures.

Importing fixture functions here (rather than into individual test
modules) makes them available to every test in this directory without
triggering a false-positive "redefinition" lint on the test module's own
fixture-name parameters.
"""

from tests.fixtures.persistence import (  # noqa: F401
    alias_registry,
    fake_pool,
    survey_form_csv,
    survey_form_postgres,
)
