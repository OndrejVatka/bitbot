FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci

# Copy source and build
COPY dashboard/ .
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

# --- Production image ---
FROM node:20-alpine

WORKDIR /app

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static .next/static

EXPOSE 3000

ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

CMD ["node", "server.js"]
