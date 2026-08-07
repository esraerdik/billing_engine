#!/bin/sh
set -e

# Container her ayağa kalktığında (dev'de `docker compose up`, prod'da
# platformun kendi başlatmasında) şema güncel ve static dosyalar hazır
# olsun diye otomatik çalışır — "tek komutla ayağa kalksın" hedefinin
# parçası. Postgres henüz hazır değilse `depends_on: condition:
# service_healthy` (docker-compose.yml) bu adımdan önce bekletir.
python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec "$@"
