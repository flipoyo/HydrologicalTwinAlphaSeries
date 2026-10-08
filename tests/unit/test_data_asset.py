from pathlib import Path

import pytest

from HydrologicalTwinAlphaSeries.domain import DataAsset


def test_data_asset_roundtrip_mapping():
    asset = DataAsset(
        name="safran-precipitation",
        resolver="dvc",
        target="data/safran",
        locator="data/safran.dvc",
        kind="climate",
        format="netcdf",
        state="md5:abc123",
        metadata={"variable": "precipitation", "unit": "mm/day"},
    )

    restored = DataAsset.from_mapping(asset.to_mapping())

    assert restored == asset
    assert restored.metadata["variable"] == "precipitation"


def test_materialized_path_is_relative_to_repo_root():
    asset = DataAsset(name="obs", resolver="file", target="datasets/obs.csv")

    assert asset.materialized_path("/tmp/data-repo") == Path("/tmp/data-repo/datasets/obs.csv")


@pytest.mark.parametrize("target", ["/absolute/path", "../outside", "data/../../outside"])
def test_target_cannot_escape_gitrepo(target):
    with pytest.raises(ValueError, match="relative path inside the GitRepo"):
        DataAsset(name="bad", resolver="file", target=target)


def test_mapping_rejects_unknown_fields():
    with pytest.raises(ValueError, match="unexpected DataAsset fields"):
        DataAsset.from_mapping(
            {
                "name": "obs",
                "resolver": "file",
                "target": "data/obs.csv",
                "credentials": "must-not-be-declared-here",
            }
        )


def test_mapping_requires_identity_fields():
    with pytest.raises(ValueError, match="missing required DataAsset field: resolver"):
        DataAsset.from_mapping({"name": "obs", "target": "data/obs.csv"})
