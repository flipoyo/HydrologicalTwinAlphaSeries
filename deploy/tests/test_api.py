"""Tests for the Django quick-deployment API.

These tests exercise the REST endpoints in isolation using Django's
test client.  No real CaWaQS data directories are needed; the test
initialises a minimal HydrologicalTwin via the ``/api/init/`` endpoint.
"""

import os
import sys

# Ensure the deploy directory is on the Python path so Django can find
# hydrotwin_web and api packages.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hydrotwin_web.settings")

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from api import twin_store  # noqa: E402


def _sample_init_payload(tmp_dir: str):
    return {
        "config_geom": {
            "ids_compartment": [1],
            "resolutionNames": {1: [["AQ_LAYER"]]},
            "ids_col_cell": {1: 0},
            "obsNames": {},
            "obsIdsColCells": {},
            "obsIdsColNames": {},
            "obsIdsColLayers": {},
            "obsIdsCell": {},
            "extNames": {},
            "extIdsColNames": {},
            "extIdsColLayers": {},
            "extIdsColCells": {},
        },
        "config_proj": {
            "json_path_geometries": "geometry.json",
            "projectName": "demo",
            "cawOutDirectory": tmp_dir,
            "startSim": 2000,
            "endSim": 2001,
            "obsDirectory": tmp_dir,
            "regime": "annual",
        },
        "out_caw_directory": tmp_dir,
        "obs_directory": tmp_dir,
    }


class HealthEndpointTest(SimpleTestCase):
    def test_health_returns_ok(self):
        client = APIClient()
        resp = client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertIn("version", resp.json())

    def test_health_reports_twin_not_initialised(self):
        twin_store.set_twin(None)
        client = APIClient()
        resp = client.get("/api/health/")
        self.assertFalse(resp.json()["twin_initialised"])


class InitEndpointTest(SimpleTestCase):
    def setUp(self):
        twin_store.set_twin(None)

    def test_init_creates_twin(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = APIClient()
            resp = client.post(
                "/api/init/",
                data=_sample_init_payload(tmp),
                format="json",
            )
            self.assertEqual(resp.status_code, 201)
            self.assertEqual(resp.json()["status"], "initialised")
            self.assertIsNotNone(twin_store.get_twin())

    def test_init_rejects_missing_fields(self):
        client = APIClient()
        resp = client.post("/api/init/", data={}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.json())


class CompartmentsEndpointTest(SimpleTestCase):
    def setUp(self):
        twin_store.set_twin(None)

    def test_compartments_503_when_no_twin(self):
        client = APIClient()
        resp = client.get("/api/compartments/")
        self.assertEqual(resp.status_code, 503)

    def test_compartments_returns_empty_list(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = APIClient()
            client.post("/api/init/", data=_sample_init_payload(tmp), format="json")
            resp = client.get("/api/compartments/")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json(), [])

    def test_get_compartment_404_for_missing(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            client = APIClient()
            client.post("/api/init/", data=_sample_init_payload(tmp), format="json")
            resp = client.get("/api/compartments/999/")
            self.assertEqual(resp.status_code, 404)
