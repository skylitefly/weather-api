#!/bin/sh

if [ "$1" = cron ]; then
  printenv >> /etc/environment
  ./manage.py crontab add
fi

exec "$@"
