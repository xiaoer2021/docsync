# ---------- 构建前端 ----------
FROM node:22-alpine AS build

WORKDIR /app

# 依赖层单独缓存：只改业务代码时不用重装 node_modules
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- 运行 ----------
FROM nginx:stable-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
