# Single-stage image: build the static site, then serve it with Vite's preview
# server. Preview (unlike a bare static server) applies the /api -> VITE_API_TARGET
# proxy from vite.config.js, so the browser only ever talks to this origin and the
# API stays same-origin (no CORS, no hard-coded backend host baked into the build).
FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
RUN npm run build
EXPOSE 3000
# Proxy target defaults to the compose service name; override for other topologies.
ENV VITE_API_TARGET=http://api:8000
CMD ["npm", "run", "preview"]
