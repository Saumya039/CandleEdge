FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG BACKEND_URL=http://backend:8000
ENV BACKEND_URL=$BACKEND_URL
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production BACKEND_URL=http://backend:8000
COPY --from=build /app ./
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
