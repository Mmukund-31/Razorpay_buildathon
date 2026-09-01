# Build context is frontend/ itself (unlike backend/Dockerfile, this one needs nothing from
# outside the frontend directory).
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
# VITE_API_BASE_URL is baked in at build time — for docker-compose, leave it unset so the
# frontend keeps using relative "/api/..." paths, proxied by nginx below to the backend
# container. For a split-origin deploy (Render), pass --build-arg to set it instead.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
