from django.core.management.base import BaseCommand
from django.utils import timezone

from weather.cron import fetch_and_cache_all_metar_taf


class Command(BaseCommand):
    help = "Fetch NOAA METAR/TAF data and refresh the weather cache."

    def handle(self, *args, **options):
        started_at = timezone.now()
        self.stdout.write(f"[{started_at.isoformat()}] Weather cache refresh started.")
        summary = fetch_and_cache_all_metar_taf(emit=self.stdout.write)
        finished_at = timezone.now()
        elapsed = (finished_at - started_at).total_seconds()
        self.stdout.write(
            "Weather cache summary: "
            f"metar_cached={summary['metar']['cached']} "
            f"taf_cached={summary['taf']['cached']} "
            f"backfill_found={(summary['backfill'] or {}).get('found', 0)} "
            f"elapsed_seconds={elapsed:.2f}"
        )
        self.stdout.write(self.style.SUCCESS(f"[{finished_at.isoformat()}] Weather cache refreshed."))
