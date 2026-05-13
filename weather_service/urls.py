from django.urls import include, path

from weather import views

urlpatterns = [
    path("healthz/", views.health, name="health"),
    path("api/", include("weather.urls")),
]
