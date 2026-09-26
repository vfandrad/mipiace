# Backend Mi Piace — FastAPI + SQLAlchemy async
#
# Fixa 3.12 (e não "latest") porque psycopg/pydantic-core precisam de wheel
# pronta: numa imagem com Python recém-lançado o build cai para compilação.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Camada de dependências separada: mudar código não reinstala tudo.
# requirements.lock.txt (não requirements.txt) de propósito: a imagem precisa
# de versão exata e reproduzível, não da faixa aberta que a máquina de dev usa
# (ver o comentário em requirements.txt — dev roda um Python mais novo que
# ainda não tem wheel pronta para as versões fixadas aqui).
COPY requirements.lock.txt ./
RUN pip install --upgrade pip && pip install -r requirements.lock.txt

COPY app ./app
COPY db ./db

# Não rodar como root.
RUN useradd --create-home --uid 1000 mipiace && chown -R mipiace:mipiace /app
USER mipiace

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
