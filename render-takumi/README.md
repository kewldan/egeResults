# render-takumi — рендерер карточек результатов

Маленький HTTP-сервис на **Bun + [takumi-js](https://github.com/kane50613/takumi)**, который
рисует красивую PNG-карточку с результатами ЕГЭ ученика. Бот ([ege-notifier](../))
дёргает его по HTTP и отправляет картинку пользователю — «можно выложить в сторис».

## Эндпоинты

```
GET  /                      — галерея карточек (превью + примеры curl)
GET  /cards/<slug>.png      — карточка с мок-данными (?scale=1..4, по умолчанию 2)
POST /cards/<slug>.png      — карточка с данными из JSON-тела (мержится поверх мок)
```

Карточки (`slug`): `summary` (сводная: сумма баллов + список предметов — её и шлёт
бот) и `russian` (одна дисциплина крупно). Тело POST для `summary`:

```bash
curl -X POST http://localhost:3000/cards/summary.png?scale=2 \
  -H 'content-type: application/json' \
  -d '{"exam":"ЕГЭ · 2026","totalLabel":"Сумма баллов","total":283,"maxTotal":300,
       "subjects":[{"name":"Математика","score":98},{"name":"Русский язык","score":94},
                   {"name":"Информатика","score":91}],"name":"Иванова"}' \
  --output card.png
```

## Запуск

```bash
bun install
bun run serve            # http://localhost:3000  (PORT переопределяет порт)
# bun run dev            # с авто-перезапуском
```

В Docker сервис поднимается вместе с ботом (`docker compose up -d --build`,
сервис `card-renderer`); бот находит его по адресу `http://card-renderer:3000`
(переменная `CARD_RENDERER_URL`).

## Шрифты

takumi не имеет системного фолбэка, а дизайнерские шрифты (Space Grotesk / Space
Mono) — только латиница. Поэтому к ним зарегистрированы кириллические компаньоны
(Manrope / JetBrains Mono) — см. `src/fonts.ts`. Все `.ttf` лежат в `fonts/`.
