"""L3 · services — a file-based geo provider, with no QGIS involved.

:class:`FileGeoProvider` satisfies the ``get_layer(layer_name)`` protocol that
``HydrologicalTwin.load`` needs, by reading each layer from a file with
geopandas. It is the provider a script, a server or the ``htas`` command line
uses where CaWaQS-ViZ would use QGIS layers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Union

import geopandas as gpd

__all__ = ["FileGeoProvider"]


class FileGeoProvider:
    """Serve GeoDataFrames by layer name from a ``name -> file path`` mapping."""

    def __init__(self, layer_paths: Mapping[str, Union[str, Path]]) -> None:
        self._layer_paths: Dict[str, str] = {
            str(name): str(path) for name, path in layer_paths.items()
        }
        self._cache: Dict[str, gpd.GeoDataFrame] = {}

    @property
    def layer_names(self) -> list:
        return sorted(self._layer_paths)

    def get_layer(self, layer_name: str) -> gpd.GeoDataFrame:
        if layer_name in self._cache:
            return self._cache[layer_name]
        if layer_name not in self._layer_paths:
            raise ValueError(
                f"No file path configured for layer '{layer_name}'. "
                f"Available: {self.layer_names}"
            )
        path = Path(self._layer_paths[layer_name])
        if not path.is_file():
            raise FileNotFoundError(f"Layer '{layer_name}': file not found: {path}")
        gdf = gpd.read_file(path)
        self._cache[layer_name] = gdf
        return gdf
