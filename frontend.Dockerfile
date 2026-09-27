# Production frontend: build the React app, then serve it with Caddy.
# Caddy also proxies /api to the backend (same origin, no CORS) and gets HTTPS certificates
# automatically once DOMAIN is set.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund --loglevel=error
COPY public ./public
COPY src ./src
# empty = call the API on the same site (/api/...), which Caddy forwards to the backend
ENV REACT_APP_API_BASE=""
RUN npm run build

FROM caddy:2-alpine
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/build /srv
