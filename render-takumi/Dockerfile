# syntax=docker/dockerfile:1
#
# Сервис-рендерер карточек результатов (Bun + takumi-js). Бот ходит к нему по HTTP
# (POST /cards/summary.png) и получает PNG. Образ glibc (oven/bun:1, Debian), чтобы
# нативный модуль takumi (@takumi-rs/core-linux-x64-gnu) подтянулся без музловых
# сюрпризов.

FROM oven/bun:1 AS deps
WORKDIR /app
# Слой зависимостей: только манифесты → кешируется, пока не менялись package/lock.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

FROM oven/bun:1
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000
COPY --from=deps /app/node_modules ./node_modules
COPY package.json bun.lock tsconfig.json ./
COPY src ./src
COPY fonts ./fonts
EXPOSE 3000
# oven/bun образ уже содержит непривилегированного пользователя `bun`.
USER bun
CMD ["bun", "run", "src/server.tsx"]
