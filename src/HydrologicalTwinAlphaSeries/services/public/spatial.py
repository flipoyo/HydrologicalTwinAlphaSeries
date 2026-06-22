import os

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union
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

    def buildAqOutcropping(self, exd, aq_compartment, save=True, coverage_threshold=0.5):
        """
        Identify aquifer cells that outcrop at the land surface.

        Starts with all cells from the topmost layer (layer 0), then adds cells from
        deeper layers that are not already covered by shallower cells. This captures
        areas where older geological formations are exposed at the surface.

        Coverage is decided by an **areal-overlap fraction**, not a centroid
        point-in-polygon test. For each deeper cell we measure how much of its
        footprint is overlapped by the union of already-accumulated (shallower)
        cells; if that fraction is >= ``coverage_threshold`` the cell is treated
        as buried and excluded. A single centroid is a poor proxy for a cell's
        footprint: on a resolution mismatch the centroid falls in the seam
        between shallower cells (so a buried cell would be wrongly kept), and on
        exact grid alignment the centroid lands on a shared edge/vertex, which
        Shapely's interior-only ``contains`` rejects (so a perfectly stacked cell
        would be wrongly kept). The area-fraction test fixes both.

        :param exd: ExplorerData instance containing post_process_directory path
        :param aq_compartment: Aquifer Compartment object with mesh attribute
        :param save: If True, saves outcropping cell IDs to OUTPCROOPCELLSLIST.dat
        :param coverage_threshold: Minimum fraction (in ``(0, 1]``) of a deeper
            cell's footprint area that must be overlapped by shallower cells for
            it to count as buried (and thus excluded). Default ``0.5`` (a cell
            more than half-buried is treated as buried). This is a hydrogeology
            choice — raise it to keep more partially-overlapping cells, lower it
            to drop them.
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
                # STRtree (Shapely 2.x) gives an O(log N) candidate prefilter:
                # query each deeper cell's FOOTPRINT (not its centroid) for the
                # already-accumulated shallower cells it intersects, then decide
                # burial by overlap area. No global unary_union is built — only
                # the few candidates the tree returns for one cell are unioned.
                outcrop_geoms = [out_cell.geometry for out_cell in outcropCells]
                tree = STRtree(outcrop_geoms)

                for cell in layer.layer:
                    geom = cell.geometry
                    cell_area = geom.area

                    # Degenerate footprint: cannot compute a fraction; treat as
                    # not buried (poke-through) rather than divide by zero.
                    if cell_area <= 0:
                        outcropCells.append(cell)
                        count += 1
                        continue

                    candidate_idx = tree.query(geom, predicate="intersects")
                    if candidate_idx.size == 0:
                        covered_area = 0.0
                    else:
                        covering = unary_union(
                            [outcrop_geoms[i] for i in candidate_idx]
                        )
                        covered_area = geom.intersection(covering).area

                    if covered_area / cell_area < coverage_threshold:
                        outcropCells.append(cell)
                        count += 1

                print(f"Added {count} cells")

        if save:
            with open(savepath, "w") as f:
                for cell in outcropCells:
                    f.write(f"{cell.id_abs}\n")

        return outcropCells
