from ._vitest import run_vitest


def test_schema_form_vitest():
    run_vitest("src/lib/components/schema-form/SchemaForm.test.ts")
