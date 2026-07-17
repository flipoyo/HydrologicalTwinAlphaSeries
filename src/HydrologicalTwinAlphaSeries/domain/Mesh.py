import os
from typing import Dict, List

import geopandas as gpd
import pandas as pd

from HydrologicalTwinAlphaSeries.config.constants import reversed_module_caw

sep = os.sep  # Ensure compatibility with different OS path separators


class Mesh:
    """
    Mesh class

    .. NOTE:: A single Mesh() is an attribute of the Compartment class. The mesh attribute
        of the Mesh() class is a dictionary containing all the layers of the mesh,
        identified by a key from 0 to n (0 being the most recent layer in the case of the
        aquifer compartment).
    """

    def __init__(
        self,
        id_compartment: int,
        layers_gis_name: List[str],
        layer_gdfs: Dict[str, gpd.GeoDataFrame],
        config,
        out_caw_directory: str
    ):
        """
        Initialize the Mesh.

        :param id_compartment: Compartment ID
        :type id_compartment: int
        :param layers_gis_name: List of gis layer names needed to build mesh
        :type layers_gis_name: List[str]
        :param layer_gdfs: Dictionary mapping layer names to GeoDataFrames
        :type layer_gdfs: Dict[str, gpd.GeoDataFrame]
        :param config: configuration class
        :type config: ConfigGeometry
        :param out_caw_directory: CaWaQS output directory
        :type out_caw_directory: str
        """
        super().__init__()

        print("Building mesh")
        self.id_compartment = id_compartment
        self.layers_gis_name = layers_gis_name
        self.layer_gdfs = layer_gdfs
        self.config = config
        self.out_caw_directory = out_caw_directory
        self.mesh = self.GetMesh()
        self._assign_global_ids()
        self.ncells = self.getNCells()

    def __repr__(self):
        return f"{self.layers_gis_name} : {self.mesh}"

    def getNCells(self):
        """
        Get number of cells in mesh

        :return: number of cell in mesh
        :rtype: int
        """
        ncells = 0
        for layer in self.mesh.keys():
            ncells += self.mesh[layer].ncells

        return ncells

    @property
    def hyd_corresp_missing(self):
        return any(layer._hyd_corresp_missing for layer in self.mesh.values())

    def getIdMax(self):
        """
        Get Max cell id abs in layer
        """
        max_id_per_layer = []

        for id_lay, layer in self.mesh.items():
            max_id_per_layer.append(max([cell.id for cell in layer.layer]))

        return max(max_id_per_layer)

    def getIdMin(self):
        """
        Get Max cell id abs in layer
        """
        min_id = []

        for id_lay, layer in self.mesh.items():
            min_id.append(min([cell.id for cell in layer.layer]))

        return min(min_id)

    def getCellIdVector(self):
        """
        Return CaWaQS-ordered list of absolute cell IDs.

        This matches exactly the column order of CaWaQS simulation matrices.
        """
        ids = []
        for layer in self.mesh.values():          # layer order
            for cell in layer.layer:              # CaWaQS cell order
                ids.append(cell.id)
        return ids

    def _assign_global_ids(self):
        """Populate every cell's ``id_abs`` with its absolute CaWaQS id.

        ``id_abs`` is the 1-based row index of the cell in the CaWaQS binary
        simulation matrix (CaWaQS ``ID_ABS``, unique across all layers). The
        cell already carries this value in ``cell.id``: for AQ it is loaded
        straight from the mesh GIS ``Id_ABS`` column, and for HYD it is mapped
        from the GIS id through ``HYD_corresp_file.txt`` in ``buildLayer``.
        Every historical matrix lookup already indexes ``data[cell.id - 1]``
        (see ``budget.py`` / ``dispatch.py``), i.e. the matrix is keyed by the
        absolute id, NOT by gdf-iteration order.

        So ``id_abs`` is simply an explicit alias of ``cell.id``. We do **not**
        derive it from ``getCellIdVector()`` position: the mesh is built by
        iterating the GIS gdf, whose row order need not match the CaWaQS
        ``ID_ABS`` order (real projects ship meshes that are not ``Id_ABS``-
        sorted — e.g. the first gdf row can be ``Id_ABS == 435``). Keying off
        position would mis-map every row on such a mesh.
        """
        for layer in self.mesh.values():
            for cell in layer.layer:
                cell.id_abs = cell.id

    class Layer:
        """
        Layer class
        """
        def __init__(
            self,
            id_compartment: int,
            layer_gis_name: str,
            gdf: gpd.GeoDataFrame,
            config,
            out_caw_directory: str
        ):
            """
            Initialize the Layer.

            :param id_compartment: Compartment ID
            :type id_compartment: int
            :param layer_gis_name: Name of the GIS layer
            :type layer_gis_name: str
            :param gdf: GeoDataFrame containing the layer data
            :type gdf: gpd.GeoDataFrame
            :param config: Configuration object
            :param out_caw_directory: CaWaQS output directory
            :type out_caw_directory: str
            """
            self.id_compartment = id_compartment
            self.out_caw_directory = out_caw_directory
            self._hyd_corresp_missing = False
            self.crs = gdf.crs           # pyproj.CRS or None — stored before cells are built
            self.layer = self.buildLayer(layer_gis_name, gdf, config)
            self.ncells = len(self.layer)

        def __repr__(self):
            return f"Layer count {self.ncells} cells"

        class Cell:
            def __init__(self, id_compartment, id_cell, geometry, id_abs=None, id_gis=None):
                self.id = id_cell  # id int of the cells
                self.id_abs = id_abs
                # id_gis: the id the user's own vector layer carries (what they see
                # in QGIS / their attribute table). For HYD it is the pre-translation
                # GIS reach id; for AQ/WATBAL/other (and the HYD fallback) it equals
                # id_abs. Carried here so output sites can relabel ID_ABS -> ID_GIS
                # without re-reading HYD_corresp_file.txt (see design D1).
                self.id_gis = id_gis
                self.geometry = geometry  # shapely geometry
                self.area = geometry.area  # in meters (shapely uses .area property)

            def __repr__(self):
                return f"id : {self.id} ({round(self.area, 1) * 1e-4} ha)"

        def buildLayer(self, layer_gis_name: str, gdf: gpd.GeoDataFrame, config):
            """
            Build layer from GeoDataFrame.

            :param layer_gis_name: Name of the layer
            :type layer_gis_name: str
            :param gdf: GeoDataFrame containing the layer data
            :type gdf: gpd.GeoDataFrame
            :param config: Configuration object
            :return: List of Cell objects
            """
            n_col = config.idColCells[self.id_compartment]

            # Get column name from index or dict
            if isinstance(n_col, str):
                col_name = n_col
            elif isinstance(n_col, int):
                col_name = gdf.columns[n_col]
            elif isinstance(n_col, dict):
                n_col = n_col[layer_gis_name]
                if isinstance(n_col, int):
                    col_name = gdf.columns[n_col]
                else:
                    col_name = n_col
            else:
                col_name = gdf.columns[int(n_col)]

            layer = []
            print("Building layer ...", flush=True)

            if self.id_compartment != reversed_module_caw["HYD"]:
                for idx, row in gdf.iterrows():
                    id_cell = row[col_name]

                    if id_cell >= 0:
                        geometry_cell = row.geometry

                        # AQ / WATBAL / other: GIS id == ABS id, so id_gis == id_cell.
                        layer.append(
                            self.Cell(
                                self.id_compartment, id_cell, geometry_cell,
                                id_gis=id_cell,
                            )
                        )

            else:
                try:
                    corr_file = self.readHydCorrespfile(self.out_caw_directory)
                    for idx, row in gdf.iterrows():
                        id_gis = row[col_name]
                        id_int = corr_file["ID_ABS"].loc[id_gis]
                        geometry_cell = row.geometry

                        # HYD: id is the translated ABS id; keep the pre-translation
                        # GIS id (read one line up) so output can relabel back to it.
                        layer.append(
                            self.Cell(
                                self.id_compartment, id_int, geometry_cell,
                                id_gis=id_gis,
                            )
                        )

                except FileNotFoundError as e:
                    print(
                        f"WARNING: {e}\n"
                        "Falling back to GIS IDs for HYD mesh. "
                        "HYD simulation outputs (Q, H) will not be readable.",
                        flush=True,
                    )
                    self._hyd_corresp_missing = True
                    for idx, row in gdf.iterrows():
                        id_cell = row[col_name]
                        if id_cell >= 0:
                            geometry_cell = row.geometry
                            # HYD fallback: no inward translation, so the raw id is
                            # already the GIS id — id_gis == id_abs, relabel is a no-op.
                            layer.append(
                                self.Cell(
                                    self.id_compartment, id_cell, geometry_cell,
                                    id_gis=id_cell,
                                )
                            )

            return layer

        def readHydCorrespfile(self, out_caw_directory):
            print(f"reading hyd corresp file : {out_caw_directory}")
            corresp_file_path = out_caw_directory + sep + "HYD_corresp_file.txt"
            if not os.path.isfile(corresp_file_path):
                raise FileNotFoundError(
                    f"File {corresp_file_path} not found. "
                    "Check your CaWaQS command file: either you didn't request any "
                    "HYDraulic outputs "
                    "(nor discharge, nor water depth) or you requested FORMATTED results that "
                    "CaWaQS-Viz doesn't handle yet. In the former case, request "
                    "UNFORMATTED outputs."
                )

            corr = pd.read_csv(corresp_file_path, index_col=2, sep=r"\s+")

            return corr

    def GetMesh(self):
        """
        Build mesh from GeoDataFrames

        :return: layers dictionary
        :rtype: dict
        """

        layers = {}

        for id_layer, layer_gis_name in enumerate(self.layers_gis_name):
            gdf = self.layer_gdfs[layer_gis_name]
            layers[id_layer] = self.Layer(
                self.id_compartment, layer_gis_name, gdf, self.config, self.out_caw_directory
            )
        return layers
