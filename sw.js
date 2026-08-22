const CACHE="cartellino-v8-20260822";
const SHELL=["./","./index.html","./catalog.generated.json","./manifest.webmanifest","./icons/icon-180.png","./icons/icon-192.png","./icons/icon-512.png"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)));self.skipWaiting();});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim();});
self.addEventListener("fetch",e=>{
 const u=new URL(e.request.url); if(u.origin!==location.origin)return;
 if(u.pathname.endsWith("catalog.generated.json")){
  e.respondWith(fetch(e.request,{cache:"no-store"}).then(r=>{const x=r.clone();caches.open(CACHE).then(c=>c.put(e.request,x));return r;}).catch(()=>caches.match(e.request)));return;
 }
 e.respondWith(fetch(e.request).then(r=>{const x=r.clone();caches.open(CACHE).then(c=>c.put(e.request,x));return r;}).catch(()=>caches.match(e.request)));
});