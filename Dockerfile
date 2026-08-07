# Django 6.0, Python >=3.12 gerektiriyor; geliştirme makinesiyle aynı
# sürüm (3.13) kullanılarak dev/production paritesi korunuyor.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1

WORKDIR /app

# Bağımlılıklar kaynak koddan önce kopyalanır: kaynak kod değiştiğinde
# `pip install` katmanı yeniden çalışmaz (Docker layer cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Root olmayan bir kullanıcıyla çalıştır (production güvenlik pratiği).
# `chmod +x` yerine ENTRYPOINT'te `sh entrypoint.sh` kullanılıyor çünkü
# geliştirme sırasında proje klasörü bind-mount edildiğinde (bkz.
# docker-compose.yml) Windows'ta checkout edilen dosyanın execute biti
# bu chmod'u ezip "Permission denied" hatası verebiliyor.
RUN adduser --disabled-password --no-create-home appuser \
    && mkdir -p /app/staticfiles /app/generated_invoices \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["sh", "entrypoint.sh"]

# Varsayılan (production) komut: gunicorn. Render/Railway/VPS gibi
# platformlar bu Dockerfile'ı doğrudan (docker-compose olmadan)
# çalıştıracağı için varsayılanın production-grade olması önemli —
# yerel geliştirmede docker-compose.yml bunu `runserver` ile ezer.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
