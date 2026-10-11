# Multi-stage Dockerfile for IntervAI Frontend (React + Vite)
FROM node:20-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
ARG VITE_API_URL=http://localhost:8000
ARG VITE_GOOGLE_CLIENT_ID=""
ARG VITE_TURNSTILE_SITE_KEY=""
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_TURNSTILE_SITE_KEY=$VITE_TURNSTILE_SITE_KEY

RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:alpine as runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
