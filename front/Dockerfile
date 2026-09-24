# =============================================================================
# Frontend Mi Piace — build com Node, entrega com nginx.
# =============================================================================
# O Vite embute as variáveis VITE_* no bundle em tempo de build, então elas
# precisam chegar como build args (não adianta passar no `environment` do
# compose: o JS já foi gerado). Os padrões apontam para o backend local.
# =============================================================================

# --- Estágio 1: build --------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Instala dependências antes de copiar o código: cacheia a camada pesada.
# fetch-timeout/retries maiores porque a rede do Docker Desktop, nesta máquina,
# tende a enrolar no meio do download de pacotes grandes e o timeout padrão do
# npm (~5min sem receber bytes) estourava antes de a conexão retomar.
COPY package.json package-lock.json ./
RUN npm config set fetch-timeout 600000 && \
    npm config set fetch-retries 5 && \
    npm config set fetch-retry-maxtimeout 120000 && \
    npm ci --no-audit --no-fund

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_ADMIN_API_KEY=dev-local-key
# A identidade da loja entra no bundle aqui: trocar de cliente é rebuildar a
# imagem com outros args, não editar código.
ARG VITE_STORE_NAME="Mi Piace Gelateria"
ARG VITE_STORE_LOGO_URL=/logo-mipiace.png
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_ADMIN_API_KEY=$VITE_ADMIN_API_KEY
ENV VITE_STORE_NAME=$VITE_STORE_NAME
ENV VITE_STORE_LOGO_URL=$VITE_STORE_LOGO_URL

RUN npm run build

# --- Estágio 2: runtime ------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
