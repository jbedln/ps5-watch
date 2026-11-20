# PS5 Pro watch

Surveille le stock de la **PS5 Pro 2 To (CFI-7021)** chez les revendeurs français,
t'alerte sur ton téléphone, et l'achète au prix normal dès qu'elle revient.

- 11 sites : PlayStation Direct, Amazon.fr, Fnac, Darty, Boulanger, Micromania, Cultura,
  Cdiscount, Carrefour, E.Leclerc, Auchan.
- Règles : prix ≤ `max_price` (899,99 €), vendu par l'enseigne elle-même (jamais de
  marketplace), neuf uniquement, **une seule console** : dès qu'une commande passe, tout s'arrête.
- Aucun mot de passe ni numéro de carte dans le code : tout passe par ta session déjà
  connectée dans le profil Chromium du script.
- CAPTCHA, file d'attente, 3-D Secure ou page de connexion : le script ne contourne
  jamais. Il met le site en pause, te notifie et te laisse la main.

## 1. Installation

```bash
cd ~/Projects/ps5-watch
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

## 2. Alertes sur le téléphone (ntfy)

1. Installe l'app **ntfy** (App Store / Play Store).
2. Dans l'app : **+** → topic = la valeur de `ntfy.topic` dans `config.yaml`
   (un nom long et aléatoire : n'importe qui qui connaît le topic peut lire les messages).
3. Sur iPhone, autorise les notifications critiques / « Time Sensitive » pour ntfy.
   Les alertes de stock partent en priorité **urgente** (5).

## 3. Première connexion à chaque site

Le script utilise son propre profil Chromium (`./profile`), séparé de ton Chrome.
Il faut s'y connecter une fois partout :

```bash
.venv/bin/python main.py --login
```

Un onglet s'ouvre par site. Sur chacun :
- connecte-toi (coche « Rester connecté » quand c'est proposé),
- vérifie que **l'adresse de livraison** et **la carte** sont enregistrées sur le compte
  (et la carte par défaut),
- accepte ou refuse les cookies une bonne fois.

Puis appuie sur Entrée dans le terminal. Les sessions expirent parfois (surtout Amazon,
PlayStation) : tu recevras une notif « Page de connexion », il suffit de relancer `--login`.

Un seul site : `--login --sites amazon`.

## 4. Tester

**Un passage sur chaque site, tableau récap, aucun achat :**

```bash
.venv/bin/python main.py --check-once
```

**Même chose sur le produit de test (une DualSense en stock) :**

```bash
.venv/bin/python main.py --check-once --test
```

**Répétition générale du checkout, sans payer** : surveille la DualSense, l'ajoute au
panier, va jusqu'au bouton final de paiement, **ne clique pas**, notifie, puis s'arrête.

```bash
.venv/bin/python main.py --dry-run --sites amazon
```

Fais-le une fois par site, connecté, avant de lancer pour de vrai : c'est là que tu vois
si les sélecteurs du checkout tiennent. Pense à **vider le panier** après.

## 5. Lancer

```bash
.venv/bin/python main.py
```

- Polling toutes les 2 à 4 min (aléatoire), une seule fenêtre, les sites l'un après l'autre.
- Mode `assist` (défaut) : le script remplit tout, s'arrête avant le bouton final,
  t'envoie une notif et laisse la fenêtre ouverte. Tu cliques. Il détecte la page de
  confirmation et coupe tout.
- Mode `auto` (`mode: auto` dans `config.yaml`) : il clique aussi le bouton final.
  Il verrouille avant de cliquer : jamais deux commandes.
- Si le total affiché au paiement dépasse `max_price` : il annule et te prévient.

Logs : `logs/ps5watch.log` (chaque passage, chaque changement « rupture → dispo »).
État : `state.json` (dernier stock vu, sites en pause, verrou d'achat).

Après un achat, le script refuse de redémarrer. Pour relancer quand même :

```bash
.venv/bin/python main.py --reset-lock
```

## 6. En arrière-plan sur macOS (launchd)

```bash
mkdir -p logs
cp launchd/com.ps5watch.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ps5watch.plist
```

- Démarre à l'ouverture de session, redémarre après un crash, **pas** après un achat.
- `caffeinate -i` empêche le Mac de dormir tant qu'il tourne (le capot fermé, il dort quand même).
- La fenêtre Chromium s'ouvre sur ton bureau : laisse-la, c'est elle qui sert au checkout.

Arrêter :

```bash
launchctl bootout gui/$(id -u)/com.ps5watch
```

Voir si ça tourne :

```bash
launchctl print gui/$(id -u)/com.ps5watch | grep state; tail -f logs/ps5watch.log
```

Le chemin `/Users/jb/Projects/ps5-watch` est écrit en dur dans le plist : adapte-le si
tu déplaces le dossier.

## Structure

```
main.py            boucle, règles d'achat, modes (--check-once, --dry-run, --login...)
notifier.py        ntfy
config.yaml        prix max, mode, polling, topic, sites actifs, URL par site
adapters/base.py   logique commune : JSON-LD, prix, détection captcha / queue / login / 3DS, checkout
adapters/<site>.py un fichier par site : URL produit, URL test, sélecteurs, règle vendeur, étapes checkout
launchd/           plist pour tourner en fond
```

Changer l'URL d'un produit sans toucher au code :

```yaml
sites:
  amazon:
    url: https://www.amazon.fr/dp/XXXXXXXXXX
```

## Limites à connaître

- **Le checkout de chaque site n'a pas pu être testé jusqu'au bout sans tes comptes.**
  Le monitoring (stock / prix / vendeur) est testé. Les étapes de paiement sont écrites
  d'après les pages des sites : valide-les avec `--dry-run`. Si une étape casse, le script
  ne reste pas bloqué : il t'envoie « checkout planté, finis à la main » et laisse la fenêtre.
- PlayStation Direct exige un compte PSN connecté pour ajouter au panier.
- Révision CFI-7121 : depuis fin 2025, certains revendeurs (Amazon notamment) vendent la
  nouvelle révision CFI-7121 (même console, 2 To). Le script surveille la fiche CFI-7021
  sur Amazon ; pour accepter aussi la 7121, mets son URL dans `sites.amazon.url`
  (https://www.amazon.fr/dp/B0FRYBZR91).
- Les sites changent leur HTML. Si un site affiche `ERREUR` ou `?` dans `--check-once`,
  le sélecteur est à mettre à jour dans `adapters/<site>.py`.
