# HydrologicalTwinAlphaSeries API Examples

## Construction

```python
from HydrologicalTwinAlphaSeries import HydrologicalTwin
from HydrologicalTwinAlphaSeries.config import ConfigGeometry, ConfigProject

config_geom = ConfigGeometry(...)
config_proj = ConfigProject(...)

ht = HydrologicalTwin(
    config_geom=config_geom,
    config_proj=config_proj,
    out_caw_directory="/path/to/CAWAQS/OUTPUTS",
    obs_directory="/path/to/OBS",
    temp_directory="/path/to/TEMP",
)
```

## Extracting a simulation matrix

```python
resp = ht.extract_values(
    id_compartment=1,
    outtype="MB",
    param="recharge",
    syear=1990,
    eyear=2000,
    id_layer=0,
    cutsdate="1995-01-01",
    cutedate="1999-12-31",
)

print(resp.data.shape)
print(resp.dates[:3])
```

## Reading observations

```python
obs = ht.read_observations(
    id_compartment=1,
    syear=1990,
    eyear=2000,
)

print(obs.data.head())
```

## Inspecting metadata

```python
print(ht.list_compartments())
print(ht.get_observation_info(1))
```

## Inspecting the explicit frontend facade

```python
facade = ht.describe_api_facade()

print(facade.entrypoint)         # HydrologicalTwin
print(facade.primary_consumer)   # cawaqsviz
print([method.name for method in facade.frontend_methods])
```
