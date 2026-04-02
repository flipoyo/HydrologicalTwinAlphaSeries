# Quick Deployment with Django

This directory contains a minimal **Django + Django REST Framework** application
that wraps the `HydrologicalTwin` backend facade and exposes it as a REST API.

It is designed for rapid local previews, demos, and integration testing — not for
production deployment.

## Getting Started

### 1. Install deploy extras

From the repository root:

```bash
pip install -e ".[deploy]"
```

Or, if you use Pixi:

```bash
pixi run -e deploy serve
```

### 2. Run the development server

```bash
cd deploy
python manage.py runserver
```

The API is available at `http://127.0.0.1:8000/api/`.

### 3. Initialise the twin

POST your project configuration to `/api/init/`:

```bash
curl -X POST http://127.0.0.1:8000/api/init/ \
     -H "Content-Type: application/json" \
     -d '{
       "config_geom": {
         "ids_compartment": [1],
         "resolutionNames": {"1": [["AQ_LAYER"]]},
         "ids_col_cell": {"1": 0},
         "obsNames": {},
         "obsIdsColCells": {},
         "obsIdsColNames": {},
         "obsIdsColLayers": {},
         "obsIdsCell": {},
         "extNames": {},
         "extIdsColNames": {},
         "extIdsColLayers": {},
         "extIdsColCells": {}
       },
       "config_proj": {
         "json_path_geometries": "geometry.json",
         "projectName": "demo",
         "cawOutDirectory": "/tmp/out",
         "startSim": 2000,
         "endSim": 2001,
         "obsDirectory": "/tmp/obs",
         "regime": "annual"
       },
       "out_caw_directory": "/tmp/out",
       "obs_directory": "/tmp/obs"
     }'
```

### 4. Query the API

```bash
curl http://127.0.0.1:8000/api/health/
curl http://127.0.0.1:8000/api/compartments/
curl http://127.0.0.1:8000/api/compartments/1/
curl http://127.0.0.1:8000/api/compartments/1/layers/
curl http://127.0.0.1:8000/api/compartments/1/observations/
```

## Available Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health/` | Service health and twin status |
| `POST` | `/api/init/` | Initialise the in-memory twin |
| `GET`  | `/api/compartments/` | List all compartments |
| `GET`  | `/api/compartments/<id>/` | Compartment metadata |
| `GET`  | `/api/compartments/<id>/layers/` | Layers of a compartment |
| `GET`  | `/api/compartments/<id>/observations/` | Observation metadata |

## Running Tests

```bash
cd deploy
python manage.py test tests
```

Or via Pixi:

```bash
pixi run -e deploy test-deploy
```

## CaWaQS-ViZ Compatibility

This deployment layer is **additive** and does **not** modify any file in
`src/hydrological_twin_alpha_series/`. The core library remains unchanged
and fully compatible with the cawaqsviz QGIS plugin.

### Changes that need to be transferred to cawaqsviz

| File | What changed | Transfer needed? |
|------|-------------|-----------------|
| `pyproject.toml` | Added `[deploy]` optional-dependency group | **Yes** — add the same group so the submodule can also serve via Django. |
| `pixi.toml` | Added `deploy` feature/environment and tasks | **Optional** — only needed if cawaqsviz developers want to start the server from the submodule checkout. |
| `deploy/` (entire directory) | New Django project | **No** — lives outside `src/` and has no effect on the library. Can be present in the submodule tree without impact. |
| `.gitignore` | Added `db.sqlite3` | **Optional** — harmless to include. |
| `README.md` | Added *Quick Deployment* section | **Optional** — informational only. |

### Architectural boundary

```
┌─────────────────────────────────────────────┐
│  cawaqsviz (QGIS plugin)                    │
│                                             │
│   ┌──────────────────────────────────────┐  │
│   │  external/HydrologicalTwinAlphaSeries│  │
│   │                                      │  │
│   │  src/   ← core library (UNCHANGED)   │  │
│   │  deploy/← Django REST layer (NEW)    │  │
│   └──────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```

The `deploy/` directory is a **consumer** of the public
`hydrological_twin_alpha_series` API — exactly like cawaqsviz itself.
It imports `ConfigGeometry`, `ConfigProject`, and `HydrologicalTwin`
from the library and delegates all domain logic to them.

No internal or private APIs are used.
