from django.core.management.base import BaseCommand

from weather.cron import fetch_and_cache_all_metar_taf


class Command(BaseCommand):
    help = "Fetch NOAA METAR/TAF data and refresh the weather cache."

    def handle(self, *args, **options):
        fetch_and_cache_all_metar_taf()
        self.stdout.write(self.style.SUCCESS("Weather cache refreshed."))
