import pytest
from parrot_tools.querysource.catalog import normalize_pipeline
from parrot_tools.querysource.errors import InvalidConditionsError

EXAMPLE = {
    "queries": {
        "pokemon_all_fso_odoo": {"slug": "pokemon_all_fso_odoo_new"},
        "pokemon_warehouses_kiosks": {"slug": "pokemon_warehouses_kiosk_all_fso"},
        "node_1789431043582_1d32g": {"query": "select * from hisense.stores", "driver": "pg"},
    },
    "Join": [
        {
            "type": "left",
            "left": "pokemon_all_fso_odoo",
            "right": "pokemon_warehouses_kiosks",
            "using": ["warehouse_alias"],
        }
    ],
    "Output": [{"tableOutput": {"flavor": "postgresql", "tablename": "all_fso_odoo_new", "schema": "pokemon"}}],
}


def test_example_pipeline():
    n = normalize_pipeline(EXAMPLE)
    assert n.slug_nodes == {
        "pokemon_all_fso_odoo": "pokemon_all_fso_odoo_new",
        "pokemon_warehouses_kiosks": "pokemon_warehouses_kiosk_all_fso",
    }
    assert (
        n.raw_nodes == ["node_1789431043582_1d32g"] and n.step_names == ["Join"] and n.output_steps == ["tableOutput"]
    )
    assert not n.has_files and not n.has_sources


def test_node_defaults_to_its_name_and_sources_flag():
    n = normalize_pipeline(
        {"queries": {"epson_field_activity": {}}, "sources": [{"s3": {"bucket": "b"}}], "files": {"f": "x.csv"}}
    )
    assert n.slug_nodes == {"epson_field_activity": "epson_field_activity"} and n.has_sources and n.has_files


@pytest.mark.parametrize("bad", [[], {"queries": []}, {"queries": {"a": "slug"}}, {"queries": {}, "Output": ["x"]}])
def test_malformed(bad):
    with pytest.raises(InvalidConditionsError):
        normalize_pipeline(bad)
