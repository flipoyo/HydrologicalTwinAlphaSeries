import geopandas as gpd
import numpy as np
import pandas as pd


def assemble_single_layer_geodataframe(
    agg_df: pd.DataFrame,
    cell_ids: np.ndarray,
    cell_geometries: list,
    crs,
    id_col_name: str = "ID_ELEBU",
) -> gpd.GeoDataFrame:
    """Assemble aggregated data + layer geometry into a GeoDataFrame.

    :param agg_df: DataFrame (index=date_labels, columns=cell_ids) from aggregate_for_map
    :param cell_ids: 1D array of cell IDs for the layer
    :param cell_geometries: list of shapely geometries for the layer
    :param crs: pyproj.CRS or EPSG string
    :param id_col_name: column name for the cell ID column
    :return: GeoDataFrame with [id_col, date_columns..., geometry]
    """
    data = agg_df.T.copy()
    data = data.sort_index()
    cols = data.columns.tolist()
    data[id_col_name] = cell_ids.tolist()
    data["geometry"] = cell_geometries
    data = data.sort_values(by=id_col_name)
    data = data[[id_col_name] + cols + ["geometry"]]
    return gpd.GeoDataFrame(data, crs=crs, geometry="geometry")


def assemble_multi_layer_geodataframe(
    agg_df: pd.DataFrame,
    layers: list,
    crs,
    layer_id_offset: int = 0,
) -> gpd.GeoDataFrame:
    """Assemble aggregated data + multi-layer geometry into a GeoDataFrame.

    :param agg_df: DataFrame (index=date_labels, columns=global ``id_abs``)
        from aggregate_for_map — keyed by the unique global cell index so the
        per-layer row lookup below cannot over-match a colliding per-layer id.
    :param layers: list of LayerInfo objects
    :param crs: pyproj.CRS or EPSG string
    :param layer_id_offset: starting layer ID (0 for MB, 1 for H)
    :return: GeoDataFrame with [ID_ABS, ID_LAY, date_columns..., geometry]
    """
    data = agg_df.T

    # Use the global, unique ``id_abs`` (not the per-layer ``cell.id``) both as
    # the ID_ABS column and as the ``.loc`` selector, so a deeper-layer cell
    # whose per-layer id collides with a layer-0 cell is matched uniquely.
    id_abs = []
    layer_ids = []
    geometries = []
    for n_layer, layer_info in enumerate(layers):
        id_abs.extend(layer_info.id_abs.tolist())
        layer_ids.extend([n_layer + layer_id_offset] * layer_info.n_cells)
        geometries.extend(layer_info.cell_geometries)

    result = data.loc[id_abs].copy()
    cols = result.columns.tolist()
    result["ID_ABS"] = id_abs
    result["ID_LAY"] = layer_ids
    result["geometry"] = geometries
    result = gpd.GeoDataFrame(result, crs=crs, geometry="geometry")
    result = result[["ID_ABS", "ID_LAY"] + cols + ["geometry"]]
    result = result.sort_values(by=["ID_LAY", "ID_ABS"])
    return result
