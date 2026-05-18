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
    4: "Output_NSAT",
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

# AQ face flux direction → CaWaQS AQ_MB parameter name.
# Sign convention (CaWaQS): positive = flux entering the cell from that direction.
# Direction is named from the inside cell's perspective relative to its outside
# neighbour; the convention preserves the original feature-branch labelling
# (cf. branch_migration/frontend_50.patch L2174-2181).
AQ_FACE_DIRECTIONS = {
    "east":  "flux_x_one",
    "west":  "flux_x_two",
    "south": "flux_y_one",
    "north": "flux_y_two",
}