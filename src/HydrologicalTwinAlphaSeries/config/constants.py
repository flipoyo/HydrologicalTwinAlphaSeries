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
    # The DialogMask Water Height checkbox wires record 1 ("water_level").
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

# Semantics note for the AQ boundary-flux calendar-month total-volume mode
# (``unit="m3"``). Shipped into the GeoPackage ``provenance`` table for that mode
# so the rows of the ``monthly_values`` table are self-describing: they are
# MONTHLY totals, not daily values, and a partial first or last month totals only
# its simulated days. One constant referenced by both the code and the shipped
# provenance cannot drift from what the file actually holds (same discipline as
# ``AQ_BOUNDARY_FLUX_SIGN_CONVENTION``).
AQ_BOUNDARY_FLUX_MONTHLY_VOLUME_SEMANTICS = (
    "Values are CALENDAR-MONTH TOTAL VOLUMES in m3 (one row per year-month, "
    "the sum over that month's simulated days of daily_m3/s x 86400), stored in "
    "the 'monthly_values' table (not 'daily_values'). A partial first or last "
    "month totals only its simulated days (the true volume over the simulated "
    "portion)."
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

# Cardinal-face flip (west↔east, south↔north). Single source of truth for the
# opposing direction used when a coarse inside boundary cell must read its flux
# from a SMALLER outside neighbour: CaWaQS stores one blended flux on the coarse
# cell's shared face, but the smaller outside cell's *opposing* face is a clean
# single-sub-face value, so the read composes this flip with ``AQ_FACE_DIRECTIONS``
# to pick that outside cell's flux column. Inlining the flip in the dispatch read
# would duplicate this domain constant; it belongs here beside its sibling map.
OPPOSITE_FACE = {
    "east":  "west",
    "west":  "east",
    "south": "north",
    "north": "south",
}

# Provenance note for the AQ boundary-flux coarse-cell source correction. On a
# refined (quadtree) mesh a coarse inside boundary cell shares one side with
# several smaller outside cells, so its single stored face flux is a *blended*
# net; the exact single-sub-face crossing is instead the negated sum of those
# smaller outside neighbours' opposing faces (sign −1). Shipped into both the
# GeoPackage ``provenance`` row and the loose-CSV commented header when any face
# was sourced this way, so a value read from an outside neighbour is
# self-describing. One constant, two shipped surfaces, cannot drift (same
# discipline as ``AQ_BOUNDARY_FLUX_SIGN_CONVENTION`` /
# ``AQ_BOUNDARY_FLUX_MONTHLY_VOLUME_SEMANTICS``).
AQ_BOUNDARY_COARSE_CELL_SOURCE_NOTE = (
    "Coarse-cell source (refined mesh): where an inside boundary cell is COARSER "
    "than its outside neighbours on a side, CaWaQS stores a single blended face "
    "flux for that side. Such a face is NOT read from the inside cell; its value "
    "is the negated sum of the smaller outside neighbours' opposing-face fluxes "
    "(sign -1), the exact single-sub-face crossing. The 'outside_ids' column/mapping "
    "records those outside cell ids; an empty 'outside_ids' means the inside cell's "
    "own face was read (equal-size or fine-inside boundary, unchanged)."
)

# Dimensions constats

# Volumetric tokens. The rate tokens (``m3/s``, ``m3/j``, ``m3/mois``) are pure
# magnitude rescales (a scalar factor in ``_VOLUMETRIC_UNIT_FACTORS``, daily axis
# unchanged). ``m3`` is the odd one out: a *volume* (bare cubic metres), produced
# by a calendar-month SUM aggregation (Σ daily×86400 per month), NOT a scalar
# rescale — so it deliberately has NO entry in ``_VOLUMETRIC_UNIT_FACTORS`` below
# (see the aggregating-token note there). It is still "volumetric" for the family
# checks that gate the ×86400 vs length-passthrough distinction.
_VOLUMETRIC_UNITS = frozenset({"m3/j", "m3/s", "m3/mois", "m3"})

# Multiplicative factor converting a CaWaQS-native ``m³/s`` flux to the given
# volumetric token. ``m3/s`` is the raw pass-through (1.0); ``m3/j`` (jour) is the
# m³/day rate (× one day of seconds); ``m3/mois`` (mois) is an *average-month*
# flow RATE — every daily value rescaled by the same factor, NOT a calendar
# re-aggregation. 2_629_800 = 86400 × 365.25 / 12 (seconds in an average month).
#
# The ``m3`` calendar-month total-volume token is INTENTIONALLY ABSENT here: it
# aggregates (daily→monthly Σ of value×86400), it does not scalar-rescale, so
# there is no single factor to list. Callers that look a token up here must guard
# the aggregating token explicitly (``transform(kind='volumetric_rescale')`` and
# ``run_mask_aq_boundary`` do) rather than inventing a scalar for it.
_VOLUMETRIC_UNIT_FACTORS = {
    "m3/s": 1.0,
    "m3/j": 86400.0,
    "m3/mois": 2_629_800.0,
}

# Token → loose-CSV column-name suffix for the AQ boundary-flux export. Derived
# from the same token as the factor (above) so the values and their declared unit
# can never diverge, and two runs differing only in unit do not overwrite each
# other in one output directory. ``m3`` (calendar-month total volume) gets its
# own ``m3month`` suffix so its monthly-indexed files never collide with the
# daily-indexed ``m3d`` / ``m3mois`` rate files in the same directory.
_VOLUMETRIC_UNIT_CSV_SUFFIX = {
    "m3/j": "m3d",
    "m3/mois": "m3mois",
    "m3": "m3month",
}

# Length units (e.g. HYD Water Height). These are NOT volumetric: the ×86400
# m³/s→m³/day conversion must be skipped for them. ``m`` is the CaWaQS-native
# length unit (raw pass-through, factor 1.0); ``cm`` scales by 100.
_LENGTH_UNITS = frozenset({"m", "cm"})

# Multiplicative factor applied to native-metre length values per length token.
_LENGTH_UNIT_FACTORS = {"m": 1.0, "cm": 100.0}

_PARAM_NON_VOLUMETRIC_UNITS =   ["water_height", "water_level", "piezhead"]
