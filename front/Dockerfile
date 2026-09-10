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
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .

ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_ADMIN_API_KEY=dev-local-key
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_ADMIN_API_KEY=$VITE_ADMIN_API_KEY

RUN npm run build

# --- Estágio 2: runtime ------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1:8080/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
