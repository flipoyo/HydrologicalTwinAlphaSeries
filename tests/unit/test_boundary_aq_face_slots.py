"""L3 unit tests for the per-face structure map derived by
``build_boundary_aq_layers`` (the ``face_slots_by_cell`` fourth return value).

These pin the slot-filling rules directly at the single L3 formatting site:
``faceN_orient`` follows ``face_directions`` order; ``faceN_outid`` is filled
only for an ``EXT_cell`` (``sign == -1``) face, comma-joining multiple outside
ids; slots past ``n_faces`` are blank. The end-to-end GeoPackage materialisation
(geometry-layer ↔ values-table parity, registered-layer cleanliness, OGR column
acceptance) is covered in ``test_operations_mask_aq_boundary_gpkg.py``.
"""

from __future__ import annotations

from shapely.geometry import LineString

from HydrologicalTwinAlphaSeries.services.public.geodata_assembly import (
    build_boundary_aq_layers,
)


def _build(edge_geometries, cell_layer_ids, face_directions, face_sources):
    return build_boundary_aq_layers(
        edge_geometries=edge_geometries,
        cell_layer_ids=cell_layer_ids,
        crs="EPSG:2154",
        face_directions=face_directions,
        face_sources=face_sources,
    )


def test_mixed_int_ext_cell_slots():
    """Spec scenario "Mixed INT_cell / EXT_cell boundary cell": a two-faced cell
    with a north INT_cell face (blank outid) and a west EXT_cell face whose flux
    was sourced from smaller outside neighbours [1234, 1235] (comma-joined outid).
    """
    edge_geometries = {7: LineString([(0, 0), (0, 1)])}
    cell_layer_ids = {7: 0}
    # face_directions insertion order fixes the slot order: north → slot 1,
    # west → slot 2.
    face_directions = {7: ["north", "west"]}
    face_sources = {
        7: {
            "north": {"sign": +1, "outside_ids": []},
            "west": {"sign": -1, "outside_ids": [1234, 1235]},
        }
    }

    _entries, _faces, _outside, face_slots = _build(
        edge_geometries, cell_layer_ids, face_directions, face_sources
    )

    slots = face_slots[7]
    assert slots["n_faces"] == 2
    assert slots["face1_orient"] == "north"
    assert slots["face1_outid"] == ""            # INT_cell → blank
    assert slots["face2_orient"] == "west"
    assert slots["face2_outid"] == "1234,1235"   # EXT_cell → comma-joined ids
    assert slots["face3_orient"] == ""
    assert slots["face3_outid"] == ""


def test_slots_past_n_faces_are_blank():
    """Spec scenario "Slots past n_faces are blank": a 1-face cell fills slot 1
    and leaves face2_* / face3_* empty."""
    edge_geometries = {3: LineString([(2, 0), (2, 1)])}
    cell_layer_ids = {3: 0}
    face_directions = {3: ["south"]}
    face_sources = {3: {"south": {"sign": -1, "outside_ids": [42]}}}

    _entries, _faces, _outside, face_slots = _build(
        edge_geometries, cell_layer_ids, face_directions, face_sources
    )

    slots = face_slots[3]
    assert slots["n_faces"] == 1
    assert slots["face1_orient"] == "south"
    assert slots["face1_outid"] == "42"
    assert slots["face2_orient"] == ""
    assert slots["face2_outid"] == ""
    assert slots["face3_orient"] == ""
    assert slots["face3_outid"] == ""


def test_int_cell_face_outid_always_blank():
    """Spec scenario "outid populated only for the outside-sourced face": an
    INT_cell (sign == +1) face keeps a blank outid regardless of neighbours."""
    edge_geometries = {9: LineString([(0, 0), (1, 0)])}
    cell_layer_ids = {9: 0}
    face_directions = {9: ["east"]}
    # sign == +1 with (hypothetical) outside_ids present — must still be blank.
    face_sources = {9: {"east": {"sign": +1, "outside_ids": [100, 200]}}}

    _entries, _faces, _outside, face_slots = _build(
        edge_geometries, cell_layer_ids, face_directions, face_sources
    )

    assert face_slots[9]["face1_orient"] == "east"
    assert face_slots[9]["face1_outid"] == ""


def test_face_slots_not_attached_to_entries_gdf():
    """Design D7 (b): the entries gdf stays clean (cell_id / faces / geometry) —
    none of the seven columns is attached to the registered-layer gdf."""
    edge_geometries = {7: LineString([(0, 0), (0, 1)])}
    cell_layer_ids = {7: 0}
    face_directions = {7: ["north", "west"]}
    face_sources = {7: {"west": {"sign": -1, "outside_ids": [1234]}}}

    entries, _faces, _outside, _face_slots = _build(
        edge_geometries, cell_layer_ids, face_directions, face_sources
    )

    (_id_layer, gdf) = entries[0]
    assert set(gdf.columns) == {"cell_id", "faces", "geometry"}


def test_empty_edge_geometries_yields_empty_maps():
    """An empty input yields ([], {}, {}, {}) — no raise, empty slot map."""
    entries, faces, outside, face_slots = _build({}, {}, {}, {})
    assert entries == []
    assert faces == {}
    assert outside == {}
    assert face_slots == {}
