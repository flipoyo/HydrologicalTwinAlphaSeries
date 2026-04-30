"""Unit tests for the mask() macro dispatcher (S0 scaffold, S1 area_values, S3 polygon_cells)."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString, box

from HydrologicalTwinAlphaSeries.ht import (
    AqBoundaryResponse,
    CellSelectionResponse,
    HydBoundaryResponse,
    HydrologicalTwin,
    MaskRequest,
    ValuesResponse,
)
from HydrologicalTwinAlphaSeries.ht.api_types import InvalidStateError, TwinState
from HydrologicalTwinAlphaSeries.tools.spatial_utils import CRSMismatchError


def _twin_in_loaded_state() -> HydrologicalTwin:
    twin = HydrologicalTwin()
    twin._state = TwinState.LOADED
    return twin


def test_mask_unknown_kind_raises_value_error_naming_the_kind():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError) as exc:
        twin.mask(kind="does_not_exist")

    assert "does_not_exist" in str(exc.value)


def test_mask_unknown_kind_via_request_object_raises_value_error():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError) as exc:
        twin.mask(request=MaskRequest(kind="does_not_exist"))

    assert "does_not_exist" in str(exc.value)


def test_mask_before_loaded_state_raises_invalid_state():
    twin = HydrologicalTwin()

    with pytest.raises(InvalidStateError):
        twin.mask(kind="does_not_exist")


def test_mask_rejects_unexpected_kwargs_alongside_request():
    twin = _twin_in_loaded_state()

    with pytest.raises(TypeError):
        twin.mask(request=MaskRequest(kind="does_not_exist"), bogus_kwarg=42)


# ---------------------------------------------------------------------------
# S1 — kind="area_values" wraps extract_area()
# ---------------------------------------------------------------------------


def _area_values_kwargs(**overrides):
    base = {
        "kind": "area_values",
        "id_compartment": 1,
        "outtype": "MB",
        "param": "rain",
        "syear": 2000,
        "eyear": 2001,
    }
    base.update(overrides)
    return base


def test_mask_area_values_with_cell_ids_delegates_to_extract_area(monkeypatch):
    twin = _twin_in_loaded_state()
    captured = {}
    expected_response = ValuesResponse(data=np.zeros((3, 365)), dates=np.arange(365))

    def fake_extract_area(**kwargs):
        captured.update(kwargs)
        return expected_response

    monkeypatch.setattr(twin, "extract_area", fake_extract_area)

    response = twin.mask(**_area_values_kwargs(cell_ids=[1, 2, 3]))

    assert response is expected_response
    assert captured["id_compartment"] == 1
    assert captured["outtype"] == "MB"
    assert captured["param"] == "rain"
    assert captured["syear"] == 2000
    assert captured["eyear"] == 2001
    assert captured["id_layer"] == 0
    np.testing.assert_array_equal(captured["cell_ids"], np.array([1, 2, 3]))


def test_mask_area_values_with_both_cell_ids_and_polygon_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="either 'cell_ids' or 'polygon', not both"):
        twin.mask(**_area_values_kwargs(cell_ids=[1], polygon=object()))


def test_mask_area_values_with_neither_cell_ids_nor_polygon_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="requires either 'cell_ids' or 'polygon'"):
        twin.mask(**_area_values_kwargs())


def test_mask_area_values_missing_required_field_raises():
    twin = _twin_in_loaded_state()

    with pytest.raises(ValueError, match="non-None values for: outtype"):
        twin.mask(
            kind="area_values",
            id_compartment=1,
            param="rain",
            syear=2000,
            eyear=2001,
            cell_ids=[1, 2, 3],
        )


# ---------------------------------------------------------------------------
# S3 — kind="polygon_cells" + polygon path of "area_values"
# ---------------------------------------------------------------------------


def _twin_with_mock_compartment(monkeypatch, mesh_gdf, cell_id_col="cell_id"):
    """Twin with stubbed compartment-mesh + cell-id-column resolution.

    Bypasses configure()/load() — the dispatcher only reads the resolved
    mesh and id_col, so we mock those two helpers directly.
    """
    twin = _twin_in_loaded_state()
    monkeypatch.setattr(twin, "_resolve_mesh_gdf", lambda *_args, **_kw: mesh_gdf)
    monkeypatch.setattr(twin, "_resolve_cell_id_col", lambda *_args, **_kw: cell_id_col)
    return twin


def _grid_mesh(nx: int = 3, ny: int = 3, *, crs="EPSG:3857") -> gpd.GeoDataFrame:
    geometries = []
    ids = []
    for j in range(ny):
        for i in range(nx):
            geometries.append(box(i, j, i + 1, j + 1))
            ids.append(j * nx + i)
    return gpd.GeoDataFrame({"cell_id": ids}, geometry=geometries, crs=crs)


def test_mask_polygon_cells_returns_cell_selection_response(monkeypatch):
    mesh = _grid_mesh()
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)  # covers cells 0,1,3,4

    response = twin.mask(kind="polygon_cells", id_compartment=1, polygon=polygon)

    assert isinstance(response, CellSelectionResponse)
    assert sorted(response.cell_ids) == [0, 1, 3, 4]
    assert response.meta["id_compartment"] == 1
    assert response.meta["kind"] == "polygon_cells"


def test_mask_polygon_cells_missing_id_compartment_raises(monkeypatch):
    mesh = _grid_mesh()
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="polygon_cells", polygon=polygon)


def test_mask_polygon_cells_missing_polygon_raises(monkeypatch):
    mesh = _grid_mesh()
    twin = _twin_with_mock_compartment(monkeypatch, mesh)

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="polygon_cells", id_compartment=1)


def test_mask_polygon_cells_crs_mismatch_raises(monkeypatch):
    mesh = _grid_mesh(crs="EPSG:3857")
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)

    with pytest.raises(CRSMismatchError):
        twin.mask(
            kind="polygon_cells",
            id_compartment=1,
            polygon=polygon,
            polygon_crs="EPSG:4326",
        )


def test_mask_polygon_cells_no_polygon_crs_skips_validation(monkeypatch):
    """polygon_crs=None passes silently — CRS check defers to the frontend."""
    mesh = _grid_mesh(crs="EPSG:3857")
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)

    response = twin.mask(kind="polygon_cells", id_compartment=1, polygon=polygon)

    assert isinstance(response, CellSelectionResponse)


def test_mask_area_values_with_polygon_resolves_cells_then_delegates(monkeypatch):
    mesh = _grid_mesh()
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)  # cells 0,1,3,4
    captured = {}
    expected_response = ValuesResponse(data=np.zeros((4, 365)), dates=np.arange(365))

    def fake_extract_area(**kwargs):
        captured.update(kwargs)
        return expected_response

    monkeypatch.setattr(twin, "extract_area", fake_extract_area)

    response = twin.mask(**_area_values_kwargs(polygon=polygon))

    assert response is expected_response
    np.testing.assert_array_equal(sorted(captured["cell_ids"].tolist()), [0, 1, 3, 4])


def test_mask_area_values_with_polygon_crs_mismatch_raises(monkeypatch):
    mesh = _grid_mesh(crs="EPSG:3857")
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(0.1, 0.1, 1.9, 1.9)
    monkeypatch.setattr(twin, "extract_area", lambda **_kw: None)  # never called

    with pytest.raises(CRSMismatchError):
        twin.mask(**_area_values_kwargs(polygon=polygon, polygon_crs="EPSG:4326"))


# ---------------------------------------------------------------------------
# S5 — kind="boundary_hyd" + HydBoundaryResponse
# ---------------------------------------------------------------------------


def _hyd_network(reaches: dict, *, crs="EPSG:3857") -> gpd.GeoDataFrame:
    """Build a HYD network GeoDataFrame from a {reach_id: LineString} dict."""
    return gpd.GeoDataFrame(
        {"reach_id": list(reaches.keys())},
        geometry=list(reaches.values()),
        crs=crs,
    )


def test_mask_boundary_hyd_returns_hyd_boundary_response(monkeypatch):
    network = _hyd_network(
        {
            1: LineString([(2.0, 5.0), (8.0, 5.0)]),  # wholly inside (0..10 box)
            2: LineString([(5.0, 5.0), (15.0, 5.0)]),  # straddles boundary
            3: LineString([(20.0, 5.0), (30.0, 5.0)]),  # wholly outside
        }
    )
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")
    polygon = box(0.0, 0.0, 10.0, 10.0)

    response = twin.mask(kind="boundary_hyd", id_compartment=1, polygon=polygon)

    assert isinstance(response, HydBoundaryResponse)
    assert response.reach_ids == [2]
    assert len(response.geometries) == 1
    assert list(response.geometries[0].coords) == [(5.0, 5.0), (15.0, 5.0)]
    assert response.meta["id_compartment"] == 1
    assert response.meta["kind"] == "boundary_hyd"


def test_mask_boundary_hyd_missing_id_compartment_raises(monkeypatch):
    network = _hyd_network({1: LineString([(0.0, 0.0), (1.0, 0.0)])})
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")
    polygon = box(0.0, 0.0, 10.0, 10.0)

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="boundary_hyd", polygon=polygon)


def test_mask_boundary_hyd_missing_polygon_raises(monkeypatch):
    network = _hyd_network({1: LineString([(0.0, 0.0), (1.0, 0.0)])})
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="boundary_hyd", id_compartment=1)


def test_mask_boundary_hyd_crs_mismatch_raises(monkeypatch):
    network = _hyd_network(
        {1: LineString([(2.0, 5.0), (15.0, 5.0)])}, crs="EPSG:3857"
    )
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")
    polygon = box(0.0, 0.0, 10.0, 10.0)

    with pytest.raises(CRSMismatchError):
        twin.mask(
            kind="boundary_hyd",
            id_compartment=1,
            polygon=polygon,
            polygon_crs="EPSG:4326",
        )


def test_mask_boundary_hyd_meta_carries_inflow_outflow_signs(monkeypatch):
    """Retrofitted boundary_hyd: meta exposes inflow/outflow/signs from the new helper."""
    network = _hyd_network(
        {
            1: LineString([(15.0, 5.0), (5.0, 5.0)]),  # inflow
            2: LineString([(5.0, 5.0), (15.0, 5.0)]),  # outflow
            3: LineString([(2.0, 2.0), (8.0, 8.0)]),   # internal
        }
    )
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")
    polygon = box(0.0, 0.0, 10.0, 10.0)

    response = twin.mask(kind="boundary_hyd", id_compartment=1, polygon=polygon)

    assert response.meta["inflow_ids"] == [1]
    assert response.meta["outflow_ids"] == [2]
    assert response.meta["internal_ids"] == [3]
    assert response.meta["signs"] == {1: +1, 2: -1}
    assert sorted(response.reach_ids) == [1, 2]


def test_mask_boundary_hyd_no_boundary_reaches_returns_empty(monkeypatch):
    network = _hyd_network(
        {
            1: LineString([(2.0, 5.0), (8.0, 5.0)]),  # wholly inside
            2: LineString([(20.0, 5.0), (30.0, 5.0)]),  # wholly outside
        }
    )
    twin = _twin_with_mock_compartment(monkeypatch, network, cell_id_col="reach_id")
    polygon = box(0.0, 0.0, 10.0, 10.0)

    response = twin.mask(kind="boundary_hyd", id_compartment=1, polygon=polygon)

    assert response.reach_ids == []
    assert response.geometries == []


# ---------------------------------------------------------------------------
# S7 — kind="boundary_aq" + AqBoundaryResponse
# ---------------------------------------------------------------------------


def test_mask_boundary_aq_returns_aq_boundary_response(monkeypatch):
    """3x1 strip; polygon covers only middle cell — its 2 outside neighbours give 2 boundary edges."""
    mesh = _grid_mesh(nx=3, ny=1)
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(1.1, 0.1, 1.9, 0.9)  # contains only cell 1's centroid

    response = twin.mask(kind="boundary_aq", id_compartment=2, polygon=polygon)

    assert isinstance(response, AqBoundaryResponse)
    assert sorted(response.cell_ids) == [1, 1]
    assert len(response.edge_geometries) == 2
    assert all(edge.geom_type == "LineString" for edge in response.edge_geometries)
    assert response.meta["id_compartment"] == 2
    assert response.meta["id_layer"] == 0
    assert response.meta["kind"] == "boundary_aq"


def test_mask_boundary_aq_passes_id_layer_through(monkeypatch):
    """id_layer reaches _resolve_mesh_gdf and ends up in the response meta."""
    mesh = _grid_mesh(nx=3, ny=1)
    captured_layers = []

    def fake_resolve_mesh_gdf(id_compartment, id_layer=0):
        captured_layers.append(id_layer)
        return mesh

    twin = _twin_in_loaded_state()
    monkeypatch.setattr(twin, "_resolve_mesh_gdf", fake_resolve_mesh_gdf)
    monkeypatch.setattr(twin, "_resolve_cell_id_col", lambda *_a, **_kw: "cell_id")
    polygon = box(1.1, 0.1, 1.9, 0.9)

    response = twin.mask(
        kind="boundary_aq", id_compartment=2, polygon=polygon, id_layer=3
    )

    assert captured_layers == [3]
    assert response.meta["id_layer"] == 3


def test_mask_boundary_aq_missing_id_compartment_raises(monkeypatch):
    mesh = _grid_mesh(nx=3, ny=1)
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(1.1, 0.1, 1.9, 0.9)

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="boundary_aq", polygon=polygon)


def test_mask_boundary_aq_missing_polygon_raises(monkeypatch):
    mesh = _grid_mesh(nx=3, ny=1)
    twin = _twin_with_mock_compartment(monkeypatch, mesh)

    with pytest.raises(ValueError, match="requires both 'id_compartment' and 'polygon'"):
        twin.mask(kind="boundary_aq", id_compartment=2)


def test_mask_boundary_aq_crs_mismatch_raises(monkeypatch):
    mesh = _grid_mesh(nx=3, ny=1, crs="EPSG:3857")
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(1.1, 0.1, 1.9, 0.9)

    with pytest.raises(CRSMismatchError):
        twin.mask(
            kind="boundary_aq",
            id_compartment=2,
            polygon=polygon,
            polygon_crs="EPSG:4326",
        )


def test_mask_boundary_aq_polygon_disjoint_returns_empty(monkeypatch):
    mesh = _grid_mesh(nx=3, ny=1)
    twin = _twin_with_mock_compartment(monkeypatch, mesh)
    polygon = box(100.0, 100.0, 200.0, 200.0)

    response = twin.mask(kind="boundary_aq", id_compartment=2, polygon=polygon)

    assert response.cell_ids == []
    assert response.edge_geometries == []
