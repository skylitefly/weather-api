# Skylite Weather API
Provide METAR/TAF information to end users, and fetch NOAA every 5 minutes.

We are hosting our own deployment at https://weather.api.skylitefly.com/

## API

### GET /healthz
Health check.

### GET /api/icao/\<airport-icao\>
Return METAR and TAF information.

**Example:**
request:
```http
GET /icao/ZGGG HTTP/1.1
```
response:
```http
HTTP/1.1 200 OK
...

{"success":true,"data":{"airport":"ZGGG","metar":"ZGGG 081000Z 10002MPS 9999 -SHRA FEW016 BKN033 28/26 Q1000 NOSIG","taf":"ZGGG 080903Z 0812/0918 01005MPS 6000 SHRA FEW010 FEW026CB BKN033 TX27/0812Z TX29/0907Z TN24/0822Z TEMPO 0812/0816 2500 +TSRA SCT026CB BKN033 BECMG 0817/0818 NSW BKN033 TEMPO 0819/0824 SHRA FEW026CB BKN033"}}
```

## Configuration
| Env | Description | Required |
|-----|-------------|----------|
| SKYLITE_AVWX_TOKEN | Used as an fallback when no available data in Redis | Yes |
| SKYLITE_AVWX_BASE_URL | Base URL for avwx.rest API | No |
| SKYLITE_REDIS_WEATHER_LOCATION | Redis URL for storaging METARs | Yes |
| SKYLITE_REDIS_WEATHER_PASSWORD | Redis password | No |
| SKYLITE_REDIS_WEATHER_KEY_PREFIX | Redis key prefix | No |
