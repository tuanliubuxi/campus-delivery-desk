// Network-first navigation provides an explicit offline message without enabling offline business writes.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(
      () =>
        new Response(
          '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>校驿 · 网络不可用</title><body><main style="font-family:sans-serif;max-width:32rem;margin:4rem auto;padding:1rem"><h1>当前网络不可用</h1><p>校驿不支持离线业务提交。请恢复网络后重新打开；尚未提交的文本草稿仍保存在本设备。</p></main></body></html>',
          { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 503 },
        ),
    ),
  );
});
