# Vendor — bibliothèques tierces auto-hébergées

LM2-06 fix : ces fichiers sont copiés depuis le CDN public et servis
directement par live-mem, pour :

1. Supprimer la dépendance externe runtime (CDN compromise = JS arbitraire chez tous les clients).
2. Permettre une CSP stricte sans `script-src https://...` (LM2-05 fix).
3. Garder la maîtrise totale de la version (audit reproductible).

## Versions épinglées

| Fichier         | Version | Source                                                                  | SHA-384 (base64)                                                       |
| --------------- | ------- | ----------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `marked.min.js` | 12.0.2  | <https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js>              | `/TQbtLCAerC3jgaim+N78RZSDYV7ryeoBCVqTuzRrFec2akfBkHS7ACQ3PQhvMVi`     |
| `purify.min.js` | 3.1.6   | <https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js>       | `+VfUPEb0PdtChMwmBcBmykRMDd+v6D/oFmB3rZM/puCMDYcIvF968OimRh4KQY9a`     |

## Procédure de mise à jour

```bash
cd src/live_mem/static/vendor
curl -sSL -o marked.min.js https://cdn.jsdelivr.net/npm/marked@<NEW>/marked.min.js
curl -sSL -o purify.min.js https://cdn.jsdelivr.net/npm/dompurify@<NEW>/dist/purify.min.js

# Vérifier les hashes
for f in marked.min.js purify.min.js; do
    echo "$f sha384: $(openssl dgst -sha384 -binary "$f" | openssl base64 -A)"
done
```

Mettre à jour ce README avec les nouvelles versions/hashes.

## Pourquoi `marked` + `DOMPurify` ?

- `marked` : conversion Markdown → HTML pour les notes live et les fichiers bank.
- `DOMPurify` : sanitisation du HTML produit par `marked` (LM2-19 fix —
  marked ≥ 4 ne supporte plus l'option `sanitize`, le sanitization doit
  être faite côté client après le rendering).
