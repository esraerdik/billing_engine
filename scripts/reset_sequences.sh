#!/bin/sh
# PostgreSQL'e `loaddata` ile veri yüklendikten sonra çalıştırılır.
#
# `loaddata`, fixture'daki satırları eski (SQLite'tan gelen) PK'leriyle
# yazar; Postgres'in auto-increment sayaçları (sequence) bundan haberdar
# olmaz. Bu script her tablonun sequence'ini o tablodaki MAX(id)'nin
# üzerine çeker — hiçbir satır silinmez/değiştirilmez, sadece "bir
# sonraki otomatik ID ne olsun" sayacı düzeltilir.
#
# `web` imajına psql eklemeden, SQL'i `web` içindeki `sqlsequencereset`
# üretir, `db` container'ının (postgres:16-alpine, psql zaten dahili)
# kendi `psql`'ine boru hattıyla (pipe) iletilir — Docker mimarisi
# değişmez, `web` imajı minimal kalır.
#
# Kullanım: sh scripts/reset_sequences.sh
set -e

docker compose exec -T web python manage.py sqlsequencereset \
  accounts audit billing auth admin sessions \
  | docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

echo "Sequence reset tamamlandi."
