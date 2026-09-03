"""Tests for `_map_vendor.py`'s name -> vendored-file mapping (FEAT-522,
TASK-2785)."""
from parrot.outputs.a2ui_renderers._map_vendor import VENDORED_ASSET_PATHS


class TestMapVendor:
    def test_all_folium_default_resources_have_a_vendored_path(self):
        """Every (name, url) pair folium.Map()/MarkerCluster() declare by
        default has a corresponding local vendored file path."""
        import folium
        import folium.plugins as fp

        m = folium.Map()
        mc = fp.MarkerCluster()
        all_names = {n for n, _ in m.default_js} | {n for n, _ in m.default_css}
        all_names |= {n for n, _ in mc.default_js} | {n for n, _ in mc.default_css}
        assert all_names <= set(VENDORED_ASSET_PATHS)

    def test_vendored_files_exist_on_disk(self):
        for path in VENDORED_ASSET_PATHS.values():
            assert path.exists(), f"missing vendored asset: {path}"
