/* Service worker de l'application Véhicules.
 *
 * Stratégie :
 *  - pages HTML (navigations) : toujours le réseau, jamais de cache, afin de
 *    ne jamais afficher une page périmée ni la page d'un autre utilisateur.
 *    Hors ligne, une petite page d'information est renvoyée.
 *  - fichiers statiques du site (/static/...) : cache d'abord, puis réseau.
 *  - tout le reste (API, CDN, formulaires) : réseau uniquement.
 */
const CACHE_NAME = 'vehicules-static-v4';
// La feuille de style n'est plus pré-chargée : son adresse porte désormais
// l'empreinte de son contenu, elle est donc récupérée à la première visite.
const PRECACHE = [
  '/static/favicon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/manifest.json'
];

const OFFLINE_HTML = `<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Hors ligne – Véhicules</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f8fafc;color:#1e293b;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:1rem;text-align:center}
.box{max-width:420px}h1{font-size:1.3rem}p{color:#64748b}button{background:#2563eb;color:#fff;border:0;border-radius:.5rem;
padding:.6rem 1.2rem;font-size:1rem}</style></head><body><div class="box">
<h1>Pas de connexion</h1><p>L'application de réservation des véhicules a besoin d'Internet pour afficher le planning.</p>
<button onclick="location.reload()">Réessayer</button></div></body></html>`;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') {
    return;
  }
  const url = new URL(request.url);

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
      )
    );
    return;
  }

  if (url.origin === self.location.origin && url.pathname.startsWith('/static/')) {
    // Servir le cache tout de suite, puis le rafraîchir en arrière-plan :
    // en « cache d'abord » pur, un fichier corrigé n'atteignait jamais les
    // navigateurs déjà venus.
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(request).then((cached) => {
          const reseau = fetch(request)
            .then((response) => {
              if (response.ok) {
                cache.put(request, response.clone());
              }
              return response;
            })
            .catch(() => cached);
          return cached || reseau;
        })
      )
    );
  }
});
