from django.urls import path

from . import views

app_name = "weather"

urlpatterns = [
    path("icao/<str:airport_icao>/", views.get_weather_by_icao, name="weather-by-icao"),
    path("metar/<str:airport_icao>/", views.get_metar_by_icao, name="metar-by-icao"),
    path("taf/<str:airport_icao>/", views.get_taf_by_icao, name="taf-by-icao"),
]
