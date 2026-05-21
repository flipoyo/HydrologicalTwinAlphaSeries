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

    :param agg_df: DataFrame (index=date_labels, columns=cell_ids) from aggregate_for_map
    :param layers: list of LayerInfo objects
    :param crs: pyproj.CRS or EPSG string
    :param layer_id_offset: starting layer ID (0 for MB, 1 for H)
    :return: GeoDataFrame with [ID_ABS, ID_LAY, date_columns..., geometry]
    """
    data = agg_df.T

    cell_ids = []
    layer_ids = []
    geometries = []
    for n_layer, layer_info in enumerate(layers):
        cell_ids.extend(layer_info.cell_ids.tolist())
        layer_ids.extend([n_layer + layer_id_offset] * layer_info.n_cells)
        geometries.extend(layer_info.cell_geometries)

    result = data.loc[cell_ids].copy()
    cols = result.columns.tolist()
    result["ID_ABS"] = cell_ids
    result["ID_LAY"] = layer_ids
    result["geometry"] = geometries
    result = gpd.GeoDataFrame(result, crs=crs, geometry="geometry")
    result = result[["ID_ABS", "ID_LAY"] + cols + ["geometry"]]
    result = result.sort_values(by=["ID_LAY", "ID_ABS"])
    return result
