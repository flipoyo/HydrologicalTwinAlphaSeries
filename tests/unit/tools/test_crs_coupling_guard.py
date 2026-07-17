"""Unit tests for the CRS coupling guard.

Covers the L3 helpers (``check_point_layer_crs``, ``require_coupling``), the
domain objects that record and refuse (``Observation``, ``Extraction``), and the
enforcement sites that consume coupled points.
"""

import types
import warnings

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point, box

from HydrologicalTwinAlphaSeries.domain.Extraction import Extraction
from HydrologicalTwinAlphaSeries.domain.Observations import Observation
from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
    CRSMismatchError,
    check_point_layer_crs,
    require_coupling,
    verify_crs_match,
)

L93 = "EPSG:2154"
NTF = "EPSG:27572"

# ``Observation`` / ``Extraction`` index their config dicts by compartment id
# and (for observations) by observation type. Compartment 1 is AQ, whose
# ``reversed_module_caw`` value is not ``HYD``, so no correspondence file is read.
ID_COMPARTMENT = 1
ID_OBS = 1


def _points(crs):
    return gpd.GeoDataFrame(
        {"name": ["P1", "P2"], "cell": [1, 2], "id_pt": ["a", "b"]},
        geometry=[Point(0.5, 0.5), Point(1.5, 0.5)],
        crs=crs,
    )


def _mesh(crs):
    return gpd.GeoDataFrame(
        {"ID": [1, 2]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs=crs,
    )


def _config(cell_col_idx):
    """Minimal config stub. ``cell_col_idx`` of None means 'no cell column',
    which is the branch that would otherwise call ``get_nearest_cell()``."""
    return types.SimpleNamespace(
        # observation side — keyed by id_obs
        obsIdsColCells={ID_OBS: "2"},        # id_pt column index
        obsIdsColNames={ID_OBS: 0},          # name column index
        obsIdsColLayer={ID_OBS: None},
        obsIdsCell={ID_OBS: cell_col_idx},   # cell column index or None
        obsNames={ID_COMPARTMENT: "obs_layer"},
        # extraction side — keyed by id_compartment
        extIdsColNames={ID_COMPARTMENT: 0},
        extIdsColLayer={ID_COMPARTMENT: None},
        extIdsCell={ID_COMPARTMENT: cell_col_idx},
        extNames={ID_COMPARTMENT: "ext_layer"},
        # mesh side
        resolutionNames={ID_COMPARTMENT: [["AQ_layer1"]]},
        idColCells={ID_COMPARTMENT: "ID"},
    )


def _observation(point_crs, mesh_crs, cell_col_idx=None):
    return Observation(
        id_obs=ID_OBS,
        id_compartment=ID_COMPARTMENT,
        config=_config(cell_col_idx),
        out_caw_directory="",
        obs_gdf=_points(point_crs),
        mesh_gdfs={"AQ_layer1": _mesh(mesh_crs)},
    )


def _extraction(point_crs, mesh_crs, cell_col_idx=None):
    return Extraction(
        id_type=ID_OBS,
        id_compartment=ID_COMPARTMENT,
        config=_config(cell_col_idx),
        out_caw_directory="",
        ext_gdf=_points(point_crs),
        mesh_gdfs={"AQ_layer1": _mesh(mesh_crs)},
    )


# ---------------------------------------------------------------------------
# 5.1 — check_point_layer_crs
# ---------------------------------------------------------------------------


def test_check_point_layer_crs_agreeing_layers_returns_empty_list():
    assert check_point_layer_crs(_points(L93), {"AQ_layer1": _mesh(L93)}) == []


def test_check_point_layer_crs_names_only_the_disagreeing_mesh_layer():
    mismatches = check_point_layer_crs(
        _points(L93), {"AQ_layer1": _mesh(L93), "AQ_layer2": _mesh(NTF)}
    )

    assert len(mismatches) == 1
    point_crs, layer_name, mesh_crs = mismatches[0]
    assert layer_name == "AQ_layer2"
    assert point_crs == _points(L93).crs
    assert mesh_crs == _mesh(NTF).crs


@pytest.mark.parametrize(
    "point_crs, mesh_crs",
    [(None, L93), (L93, None), (None, None)],
    ids=["point-none", "mesh-none", "both-none"],
)
def test_check_point_layer_crs_treats_an_undefined_crs_as_a_mismatch(point_crs, mesh_crs):
    mismatches = check_point_layer_crs(
        _points(point_crs), {"AQ_layer1": _mesh(mesh_crs)}
    )

    assert len(mismatches) == 1


# ---------------------------------------------------------------------------
# 5.2 — verify_crs_match keeps its permissive None handling
# ---------------------------------------------------------------------------


def test_verify_crs_match_still_passes_silently_on_an_undefined_crs():
    verify_crs_match(None, L93)
    verify_crs_match(L93, None)
    verify_crs_match(None, None)


# ---------------------------------------------------------------------------
# 5.3 / 5.4 — Observation records, warns, and refuses only the nearest-cell path
# ---------------------------------------------------------------------------


def test_observation_with_mismatched_crs_and_no_cell_column_refuses_coupling():
    with pytest.warns(UserWarning, match="CRS mismatch"):
        obs = _observation(NTF, L93, cell_col_idx=None)

    assert obs.obs_points == []
    assert obs.coupling_refused is True
    assert obs.crs_mismatches


def test_observation_with_mismatched_crs_and_a_cell_column_still_couples():
    with pytest.warns(UserWarning, match="CRS mismatch"):
        obs = _observation(NTF, L93, cell_col_idx=1)

    assert len(obs.obs_points) == 2
    assert obs.coupling_refused is False
    assert obs.crs_mismatches


def test_observation_with_agreeing_crs_couples_by_nearest_cell_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        obs = _observation(L93, L93, cell_col_idx=None)

    assert len(obs.obs_points) == 2
    assert obs.coupling_refused is False
    assert obs.crs_mismatches == []


def test_extraction_with_mismatched_crs_and_no_cell_column_refuses_coupling():
    with pytest.warns(UserWarning, match="CRS mismatch"):
        ext = _extraction(NTF, L93, cell_col_idx=None)

    assert ext.ext_point == []
    assert ext.coupling_refused is True
    assert ext.crs_mismatches


# ---------------------------------------------------------------------------
# 5.5 / 5.6 — require_coupling raises only on a refused coupling
# ---------------------------------------------------------------------------


def test_require_coupling_raises_naming_the_disagreeing_layers():
    with pytest.warns(UserWarning):
        obs = _observation(NTF, L93, cell_col_idx=None)

    with pytest.raises(CRSMismatchError) as exc:
        require_coupling(obs, context="observation points for sim/obs comparison")

    message = str(exc.value)
    assert "AQ_layer1" in message
    assert "observation points for sim/obs comparison" in message


def test_require_coupling_raises_for_a_refused_extraction_coupling():
    with pytest.warns(UserWarning):
        ext = _extraction(NTF, L93, cell_col_idx=None)

    with pytest.raises(CRSMismatchError):
        require_coupling(ext, context="extraction points for sim/obs comparison")


def test_require_coupling_permits_attribute_column_coupling_under_a_mismatch():
    with pytest.warns(UserWarning):
        obs = _observation(NTF, L93, cell_col_idx=1)

    require_coupling(obs, context="anything")


def test_require_coupling_permits_a_compartment_without_points():
    require_coupling(None, context="anything")


def test_hydrological_regime_raises_before_reaching_np_vstack():
    """budget.py's ``np.vstack`` would raise a bare numpy ValueError on the empty
    point list a refused coupling leaves behind. The guard must precede it."""
    from HydrologicalTwinAlphaSeries.services.public.budget import Budget

    with pytest.warns(UserWarning):
        obs = _observation(NTF, L93, cell_col_idx=None)

    compartment = types.SimpleNamespace(obs=obs, compartment="AQ")

    with pytest.raises(CRSMismatchError):
        Budget().calcInteranualHVariableNumpy(
            data=np.zeros((2, 3)),
            dates=np.array(["2000-01-01"], dtype="datetime64[D]"),
            compartment=compartment,
            output_folder="",
            output_name="",
        )


# ---------------------------------------------------------------------------
# 5.7 — the guard sits at every site that reads coupled points, and nowhere else
# ---------------------------------------------------------------------------


def test_a_refused_coupling_leaves_the_rest_of_the_compartment_usable():
    """A CRS mismatch corrupts only the point→cell coupling. The mesh, and every
    operation reading it (budget_barplot, the spatial maps, the masks), is
    untouched — which is why the guard refuses at the four coupled read-sites
    rather than at load."""
    with pytest.warns(UserWarning):
        obs = _observation(NTF, L93, cell_col_idx=None)

    mesh = obs.mesh_gdfs["AQ_layer1"]
    assert len(mesh) == 2
    assert mesh.crs == _mesh(L93).crs
    assert obs.obs_gdf.crs == _points(NTF).crs


# ---------------------------------------------------------------------------
# 5.8 — reproject_to_match is gone
# ---------------------------------------------------------------------------


def test_reproject_to_match_is_no_longer_importable():
    with pytest.raises(ImportError):
        from HydrologicalTwinAlphaSeries.tools import reproject_to_match  # noqa: F401


# ---------------------------------------------------------------------------
# 5.9 — backend-independence canary
# ---------------------------------------------------------------------------


def test_the_guard_imports_no_qgis_or_pyqt():
    """A notebook caller reaches the guard without any QGIS machinery loaded.

    Run in a fresh interpreter: the shared pytest process imports PyQt5 through
    other tests' matplotlib backends, so an in-process ``sys.modules`` scan would
    measure the session rather than this code path.
    """
    import subprocess
    import sys
    import textwrap

    script = textwrap.dedent(
        """
        import sys, types, warnings
        import geopandas as gpd
        from shapely.geometry import Point, box

        from HydrologicalTwinAlphaSeries.domain.Observations import Observation
        from HydrologicalTwinAlphaSeries.tools.spatial_utils import (
            CRSMismatchError, require_coupling,
        )

        config = types.SimpleNamespace(
            obsIdsColCells={1: "2"}, obsIdsColNames={1: 0},
            obsIdsColLayer={1: None}, obsIdsCell={1: None},
            obsNames={1: "obs_layer"},
            resolutionNames={1: [["AQ_layer1"]]}, idColCells={1: "ID"},
        )
        points = gpd.GeoDataFrame(
            {"name": ["P1"], "cell": [1], "id_pt": ["a"]},
            geometry=[Point(0.5, 0.5)], crs="EPSG:27572",
        )
        mesh = gpd.GeoDataFrame({"ID": [1]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:2154")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            obs = Observation(
                id_obs=1, id_compartment=1, config=config, out_caw_directory="",
                obs_gdf=points, mesh_gdfs={"AQ_layer1": mesh},
            )

        assert obs.obs_points == []
        assert obs.coupling_refused is True

        try:
            require_coupling(obs, context="notebook")
        except CRSMismatchError:
            pass
        else:
            raise AssertionError("guard did not raise")

        leaked = [m for m in sys.modules if m.startswith(("qgis", "PyQt5"))]
        assert not leaked, leaked
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)
