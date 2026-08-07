.PHONY: up down build migrate shell logs reset-sequences verify-sequences config

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

migrate:
	docker compose exec web python manage.py migrate

shell:
	docker compose exec web python manage.py shell

logs:
	docker compose logs -f web

# loaddata sonrasi auto-increment sayaclarini duzeltir (bkz. scripts/reset_sequences.sh)
reset-sequences:
	sh scripts/reset_sequences.sh

# reset-sequences sonrasi her tablonun sequence'inin MAX(id)'nin gerisinde
# olmadigini dogrular (bkz. scripts/verify_sequences.py)
verify-sequences:
	docker compose exec -T web python scripts/verify_sequences.py

# docker-compose.yml'nin tam yorumlanmis halini basar; tanimsiz degisken
# varsa burada uyari olarak gorunur (container baslatmadan kontrol icin)
config:
	docker compose config
