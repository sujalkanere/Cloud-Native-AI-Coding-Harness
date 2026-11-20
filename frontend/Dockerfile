# Stage 1: Build React/Vite application
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package manifests if present
COPY package.json* package-lock.json* ./

# Install dependencies and build if package.json exists; fallback to placeholder static site
RUN if [ -f package.json ]; then \
        npm install ; \
    fi

COPY . .

RUN if [ -f package.json ] && [ -d src ] && [ -f src/main.tsx ]; then \
        npm run build ; \
    else \
        mkdir -p dist && echo '<!DOCTYPE html><html><head><title>Cloud-Native AI Coding Harness</title></head><body><div id="root"><h1>Cloud-Native AI Coding Harness</h1><p>Frontend scaffolding ready.</p></div></body></html>' > dist/index.html ; \
    fi

# Stage 2: Nginx Web Server & Reverse Proxy
FROM nginx:1.27-alpine AS prod

# Remove default nginx configurations
RUN rm -rf /etc/nginx/conf.d/* /etc/nginx/sites-enabled/*

# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy compiled static assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
