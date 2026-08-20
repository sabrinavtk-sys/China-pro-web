// OCR/parser v58 real-case fix
// UI rebuild 2026-08-18b
self.addEventListener("install",()=>self.skipWaiting());
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",()=>{});
