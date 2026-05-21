import os

import geopandas as gpd
import pandas as pd
from shapely.strtree import STRtree

from HydrologicalTwinAlphaSeries.tools.spatial_utils import get_nearest_row


class Spatial:
    def __init__(self):
        pass

    def getCatchmentCellsIds(
        self,
        obs_point_geom,
        network_gdf: gpd.GeoDataFrame,
        network_col_name_cell: str,
        network_col_name_fnode: str,
        network_col_name_tnode: str,
    ):
        """
        Delineate a catchment by tracing the river network upstream from an observation point.

        Recursively traverses the network topology using node connectivity (fnode/tnode)
        to find all river cells that drain to the given point.

        :param obs_point_geom: Shapely geometry of the observation/outlet point
        :param network_gdf: GeoDataFrame containing the river network segments
        :param network_col_name_cell: Column name for cell IDs in the network layer
        :param network_col_name_fnode: Column name for from-node (upstream node)
        :param network_col_name_tnode: Column name for to-node (downstream node)
        :return: List of cell IDs (int) belonging to the upstream catchment
        """

        list_cprod = []

        # Use cached spatial index via get_nearest_row
        network_first_cell = get_nearest_row(obs_point_geom, network_gdf)
        if network_first_cell is None:
            return list_cprod

        list_cprod.append(network_first_cell[network_col_name_cell])

        direct_up_stream = self.getUpStreamSection(
            network_first_cell,
            network_gdf,
            network_col_name_fnode,
            network_col_name_tnode,
        )
        list_cprod += [cell[network_col_name_cell] for _, cell in direct_up_stream.iterrows()]

        while not direct_up_stream.empty:
            new_upstream = []
            for _, cell in direct_up_stream.iterrows():
                upstream = self.getUpStreamSection(
                    cell,
                    network_gdf,
                    network_col_name_fnode,
                    network_col_name_tnode,
                )
                if not upstream.empty:
                    new_upstream.append(upstream)
                    list_cprod += [c[network_col_name_cell] for _, c in upstream.iterrows()]

            if new_upstream:
                direct_up_stream = pd.concat(new_upstream, ignore_index=True)
            else:
                direct_up_stream = gpd.GeoDataFrame()

        return [id_cprod for id_cprod in list_cprod]

    def getUpStreamSection(
        self,
        section,
        network_gdf: gpd.GeoDataFrame,
        network_col_name_fnode: str,
        network_col_name_tnode: str,
    ) -> gpd.GeoDataFrame:
        """
        Get upstream sections from the network.

        :param section: Row representing the current section
        :param network_gdf: GeoDataFrame containing the network
        :param network_col_name_fnode: Column name for from-node
        :param network_col_name_tnode: Column name for to-node
        :return: GeoDataFrame of upstream sections
        """
        fnode = section[network_col_name_fnode]
        return network_gdf[network_gdf[network_col_name_tnode] == fnode]

    def buildAqOutcropping(self, exd, aq_compartment, save=True):
        """
        Identify aquifer cells that outcrop at the land surface.

        Starts with all cells from the topmost layer (layer 0), then adds cells from
        deeper layers whose centroids are not covered by shallower cells. This captures
        areas where older geological formations are exposed at the surface.

        :param exd: ExplorerData instance containing post_process_directory path
        :param aq_compartment: Aquifer Compartment object with mesh attribute
        :param save: If True, saves outcropping cell IDs to OUTPCROOPCELLSLIST.dat
        :return: List of Cell objects (from Mesh.Layer.Cell) that outcrop at surface
        """
        print("Building Outcropping aquifer cells...", flush=True)

        savepath = os.path.join(exd.post_process_directory, "TEMP", "OUTPCROOPCELLSLIST.dat")

        print("\tBuilding outcropping cells")

        mesh = aq_compartment.mesh.mesh
        outcropCells = list(mesh[0].layer)  # Make a copy

        for n_layer, layer in zip(mesh.keys(), mesh.values()):
            count = 0

            if n_layer != 0:
                # STRtree (Shapely 2.x) replaces a unary_union+contains check:
                # the union of thousands of polygons dominated runtime, while
                # a spatial index answers "is this centroid covered?" in O(log N).
                tree = STRtree([out_cell.geometry for out_cell in outcropCells])

                for cell in layer.layer:
                    if tree.query(cell.geometry.centroid, predicate="contains").size == 0:
                        outcropCells.append(cell)
                        count += 1

                print(f"Added {count} cells")

        if save:
            with open(savepath, "w") as f:
                for cell in outcropCells:
                    f.write(f"{cell.id_abs}\n")

        return outcropCells
