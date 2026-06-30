module_caw = {
    1: "AQ",
    2: "HYD",
    3: "WATBAL",
    4: "NSAT",
}

reversed_module_caw = inversed_module_caw = {
    value: key for key, value in module_caw.items()
}

out_caw_folder = {
    1: "Output_AQ",
    2: "Output_HYD",
    3: "Output_WATBAL",
    4: "Output_NONSAT",
}

out_caw_folder_by_name = {
    module_caw[k]: v for k, v in out_caw_folder.items()
}

ids_mesh = {
    1: [1],
    2: [2],
    3: [3],
    4: [4],
}

mesh_to_compartment = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
}

obs_types = {
    1: "Piezometer",
    2: "Station",
}

link_obs_mesh = {
    1: 1,
    2: 3,
}

# Native CaWaQS units of the HYD reach outtypes (internal-values masking):
#   HYD_Q (discharge / Flow)      → m³/s   (volumetric; ×86400 → m³/day)
#   HYD_H (water height / level)  → m      (length; no volumetric ×86400)
# nbRecs is the number of parameter-records each binary holds; the param's
# index in paramRecs[<key>] is its record index in that binary.
nbRecs = {
    "AQ_MB": 16,
    "AQ_H": 1,
    "HYD_Q": 1,
    "HYD_H": 2,
    "HYD_MB": 9,
    "WATBAL_MB": 10,
    "HDERM_Q": 1,
    "HDERM_MB": 9,
    "NONSAT_MB": 4,
}

paramRecs = {
    "WATBAL_MB": [
        "rain",
        "etp",
        "runoff",
        "inf",
        "etr",
        "direct_sout",
        "stockruiss",
        "stocksoil",
        "stockinf",
        "error",
    ],
    "HYD_Q": ["discharge"],
    # HYD_H holds nbRecs=2 records; the param's index in this list is its
    # record index in the binary (cf. temporal.decode_and_cache, enumerate).
    # Record 0 = "water_height", record 1 = "water_level"; both are lengths in
    # metres, so the length conversion path treats either as a raw m pass-through.
    # The DialogMask Water Height checkbox wires record 0 ("water_height").
    "HYD_H": ["water_height", "water_level"],
    "AQ_H": ["piezhead"],
    "AQ_MB": [
        "h_end",
        "dv_dt",
        "flux_x_one",
        "flux_x_two",
        "flux_y_one",
        "flux_y_two",
        "flux_z_one",
        "flux_z_two",
        "recharge",
        "uptake",
        "flux_direchlet",
        "flux_neumann",
        "surf_overflow",
        "flux_riv_to_aq",
        "err",
        "err_rel",
    ],
}

obs_config = {
    2: {"id_col_time": 1, "id_col_data": 3},
    1: {"id_col_time": 2, "id_col_data": 4},
}

# Canonical statement of the AQ boundary-flux sign convention. This is the single
# source of truth: the ``AQ_FACE_DIRECTIONS`` comment below references it, and it
# is *shipped* into the boundary-flux outputs (loose-CSV header line + GeoPackage
# ``provenance`` row) so a downstream reader can interpret a value's sign without
# reading source code. A comment and a shipped string that restate the same fact
# independently would drift; one constant referenced by both cannot.
AQ_BOUNDARY_FLUX_SIGN_CONVENTION = (
    "Sign convention (CaWaQS): positive = flux entering the cell. Each face "
    "direction is named from the inside cell's perspective relative to its "
    "outside neighbour; a per-cell net is the net inflow across that cell's "
    "exposed boundary faces."
)

# AQ face flux direction → CaWaQS AQ_MB parameter name.
# Sign convention is AQ_BOUNDARY_FLUX_SIGN_CONVENTION above (the canonical source):
# positive = flux entering the cell from that direction. Direction is named from
# the inside cell's perspective relative to its outside neighbour; the convention
# preserves the original feature-branch labelling (cf.
# branch_migration/frontend_50.patch L2174-2181).
AQ_FACE_DIRECTIONS = {
    "east":  "flux_x_two",
    "west":  "flux_x_one",
    "south": "flux_y_one",
    "north": "flux_y_two",
}

# Dimensions constats

_VOLUMETRIC_UNITS = frozenset({"m3/j", "m3/s", "m3/mois"})

# Multiplicative factor converting a CaWaQS-native ``m³/s`` flux to the given
# volumetric token. ``m3/s`` is the raw pass-through (1.0); ``m3/j`` (jour) is the
# m³/day rate (× one day of seconds); ``m3/mois`` (mois) is an *average-month*
# flow RATE — every daily value rescaled by the same factor, NOT a calendar
# re-aggregation. 2_629_800 = 86400 × 365.25 / 12 (seconds in an average month).
_VOLUMETRIC_UNIT_FACTORS = {
    "m3/s": 1.0,
    "m3/j": 86400.0,
    "m3/mois": 2_629_800.0,
}

# Token → loose-CSV column-name suffix for the AQ boundary-flux export. Derived
# from the same token as the factor (above) so the values and their declared unit
# can never diverge, and two runs differing only in unit do not overwrite each
# other in one output directory.
_VOLUMETRIC_UNIT_CSV_SUFFIX = {
    "m3/j": "m3d",
    "m3/mois": "m3mois",
}

# Length units (e.g. HYD Water Height). These are NOT volumetric: the ×86400
# m³/s→m³/day conversion must be skipped for them. ``m`` is the CaWaQS-native
# length unit (raw pass-through, factor 1.0); ``cm`` scales by 100.
_LENGTH_UNITS = frozenset({"m", "cm"})

# Multiplicative factor applied to native-metre length values per length token.
_LENGTH_UNIT_FACTORS = {"m": 1.0, "cm": 100.0}

_PARAM_NON_VOLUMETRIC_UNITS =   ["water_height", "water_level", "piezhead"]
