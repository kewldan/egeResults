import { Renderer } from "takumi-js/node";
import { fromJsx } from "takumi-js/helpers/jsx";
import { fonts } from "./fonts";
import { CARDS, type CardDef } from "./cards";

// Reuse a single renderer across requests — fonts are loaded only once.
const renderer = new Renderer({ fonts, loadDefaultFonts: true });

async function renderCard(card: CardDef<any>, scale: number, data: unknown): Promise<Buffer> {
  const { node } = await fromJsx(card.render(data));
  // devicePixelRatio scales the content, so grow the canvas with it for a true N× export.
  return renderer.render(node, {
    width: card.width * scale,
    height: card.height * scale,
    format: "png",
    devicePixelRatio: scale,
  });
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8" } });

const png = (buf: Buffer) =>
  new Response(buf, { headers: { "content-type": "image/png", "cache-control": "no-store" } });

function gallery(): string {
  const items = Object.entries(CARDS)
    .map(
      ([slug, c]) => `
      <figure>
        <img src="/cards/${slug}.png" alt="${c.title}" />
        <figcaption><span>${c.title}</span><code>GET·POST /cards/${slug}.png</code></figcaption>
      </figure>`,
    )
    .join("");
  return `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Liquid Glass · Takumi</title>
<style>
  body{margin:0;min-height:100vh;background:#0a0c14;color:#e9e9ec;font-family:system-ui,sans-serif;padding:56px}
  h1{font-weight:600;letter-spacing:-.01em;margin:0 0 6px}
  p{color:#74747e;margin:0 0 28px}
  .grid{display:flex;gap:44px;flex-wrap:wrap}
  figure{margin:0}
  img{width:420px;height:auto;display:block;box-shadow:0 40px 80px -28px rgba(0,0,0,.8)}
  figcaption{display:flex;flex-direction:column;gap:4px;color:#9a9aa2;font-size:14px;margin-top:16px}
  code{color:#7a5cff;font-size:12px}
  pre{background:#11131c;border:1px solid #20222e;border-radius:12px;padding:16px 18px;color:#c9c4ff;font-size:12.5px;overflow:auto;max-width:880px}
</style></head><body>
<h1>Liquid Glass — серверный рендер на Takumi</h1>
<p>Bun + takumi-js · настоящий backdrop-frost + плёночное зерно (feTurbulence) · GET = мок · POST = JSON · PNG без скруглённых углов</p>
<div class="grid">${items}</div>
<pre>curl -X POST http://localhost:${process.env.PORT ?? 3000}/cards/russian.png?scale=2 \\
  -H 'content-type: application/json' \\
  -d '{"subject":"Информатика","score":88,"max":100,"threshold":40,"name":"Соколов Пётр","ref":"№ 51-РЕЗ"}' \\
  --output card.png</pre>
</body></html>`;
}

const clampScale = (raw: string | null) => Math.min(4, Math.max(1, Number(raw ?? 2) || 2));

const server = Bun.serve({
  port: Number(process.env.PORT ?? 3000),
  async fetch(req) {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/") {
      return new Response(gallery(), { headers: { "content-type": "text/html; charset=utf-8" } });
    }

    const match = url.pathname.match(/^\/cards\/([\w-]+)\.png$/);
    if (match) {
      const card = CARDS[match[1]];
      if (!card) return json({ error: `Unknown card "${match[1]}"`, available: Object.keys(CARDS) }, 404);

      const scale = clampScale(url.searchParams.get("scale"));

      // GET → mock values.
      if (req.method === "GET") {
        return png(await renderCard(card, scale, card.mock));
      }

      // POST → merge the application/json body over the mock defaults.
      if (req.method === "POST") {
        let body: Record<string, unknown>;
        try {
          body = await req.json();
        } catch {
          return json({ error: "Invalid or empty application/json body" }, 400);
        }
        if (body === null || typeof body !== "object" || Array.isArray(body)) {
          return json({ error: "JSON body must be an object" }, 400);
        }
        return png(await renderCard(card, scale, { ...card.mock, ...body }));
      }

      return json({ error: "Method not allowed. Use GET (mock) or POST (json)." }, 405);
    }

    return json({ error: "Not found" }, 404);
  },
});

console.log(`▸ http://localhost:${server.port}`);
for (const slug of Object.keys(CARDS)) {
  console.log(`  GET  /cards/${slug}.png?scale=2        → mock`);
  console.log(`  POST /cards/${slug}.png  (json body)   → custom`);
}
