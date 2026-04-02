from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("init/", views.init_twin, name="init-twin"),
    path("compartments/", views.list_compartments, name="list-compartments"),
    path(
        "compartments/<int:id_compartment>/",
        views.get_compartment,
        name="get-compartment",
    ),
    path(
        "compartments/<int:id_compartment>/layers/",
        views.get_layers,
        name="get-layers",
    ),
    path(
        "compartments/<int:id_compartment>/observations/",
        views.get_observations,
        name="get-observations",
    ),
]
