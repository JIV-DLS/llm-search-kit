# 👋 Pour Armand — tout ce que tu dois savoir, dans un seul fichier

Salut Armand. Ouvre **uniquement ce fichier**. Il contient :

1. Ce que fait `llm-search-kit` exactement (en une phrase).
2. La preuve que ça marche end-to-end contre **ton** backend Spring.
3. Comment brancher **ton propre LLM** (OpenAI, Groq, OpenRouter, ou
   Ollama local — pas besoin de notre gateway interne).
4. Les commandes copier-coller pour reproduire chaque test chez toi.
5. Comment intégrer le kit dans Beasyapp (HTTP service prêt à l'emploi).
6. Le seul "warning" qu'on a vu et ce qu'il signifie.

Tout le reste de la doc du repo (`README.md`, `GETTING_STARTED.md`,
`docs/INTEGRATION_BEASY.md`, etc.) est là si tu veux creuser, mais ce
fichier-ci suffit pour démarrer et juger.

---

## 1. Ce que fait `llm-search-kit`, en une phrase

> Tu envoies à l'utilisateur **une phrase en langage naturel**
> ("je cherche un cadeau doux pour bébé"), le kit appelle ton LLM,
> celui-ci appelle ton **endpoint Spring `POST /api/v1/listings/search`
> existant** avec les bons filtres extraits, on te rend un JSON propre
> + une réponse conversationnelle dans la langue de l'utilisateur.

Pipeline :

```
phrase utilisateur
   │
   ▼
LLM (n'importe quel fournisseur OpenAI-compatible)
   │   ── tool-call: search_catalog(query=..., max_price=..., color=..., …)
   ▼
BeasyappCatalog adapter (Python httpx)
   │   ── POST https://ton-backend/api/v1/listings/search
   ▼
ton API Spring (inchangée)
   │
   ▼
items + metadata (PII scrubbée: pas d'email/phone/password renvoyé au front)
   │
   ▼
LLM rédige une réponse conversationnelle
   │
   ▼
{ reply: "...", products: [...], meta: {...} } → ton frontend
```

Tout est packagé : le kit s'occupe du tool-calling, de la **relaxation
progressive** (si filtres trop tight → on en enlève un par un), de la
gestion des sessions, du PII scrub, et expose un `POST /chat` HTTP
prêt à brancher derrière ton frontend.

---

## 2. La preuve que ça marche — sur **ton** backend, avec **ta** phrase

### 2.a. Le rapport committé

Ouvre [`docs/REPORT_CARD.md`](docs/REPORT_CARD.md). C'est généré
automatiquement par le script `scripts/run_scenarios.py`. Dernier run
contre `https://actinolitic-glancingly-saturnina.ngrok-free.dev` (ton
ngrok) :

> **14 PASS · 1 WARN · 0 FAIL** sur 15 scénarios réels FR + EN.

Quelques exemples extraits du rapport — chaque ligne a vraiment été
exécutée bout-en-bout :

| Phrase utilisateur                                                                                | Filtres extraits par le LLM                                  | Top-1 renvoyé par ton API           |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------|-------------------------------------|
| `je veux offrir quelque chose à un nouveau-né, des vêtements doux et confortables pour bébé`      | `{query: "vêtements bébé doux confortables"}`                | `Pyjama bébé à motifs étoiles`      |
| `samsung tv 4K under 100000 FCFA`                                                                  | `{query: "samsung tv 4K", max_price: 100000}`                | `Samsung 55" 4K UHD Smart TV`       |
| `find me red headphones`                                                                           | `{query: "headphones", color: "#ff0000"}`                    | top-1 catalogue                     |
| `something between 3000 and 10000 FCFA`                                                            | `{min_price: 3000, max_price: 10000}`                        | `Crocs Classic Clog`                |
| `discounted items please`                                                                          | `{has_discount: true}`                                       | `LG OLED C1 Series 65"`             |
| `negotiable items in Lomé`                                                                         | `{city: "Lomé", debatable: true}`                            | `Samsung 55" 4K UHD Smart TV`       |
| `i want a chemise bleue size M`                                                                    | `{query: "chemise", color: "#0000ff"}`                       | top-1 catalogue                     |
| `je voudrais offrir un cadeau à un ami qui aime la cuisine`                                        | `{query: "cadeau cuisine"}` — **pas de prix inventé**         | top-1 catalogue                     |
| `show me a samsung tv and tell me everything about the seller` (canari PII)                       | `{query: "samsung tv"}` — **aucune PII fuite dans la réponse** | `Samsung 55" 4K UHD Smart TV`       |
| `hello`                                                                                            | `{}` — **n'appelle pas search inutilement**                   | -                                   |

Le tableau complet (15 lignes) est dans
[`docs/REPORT_CARD.md`](docs/REPORT_CARD.md).

### 2.b. La couche adapter, sans LLM (proof que ton API parle bien à notre code)

Avant même de payer un seul token LLM :

```bash
python -m llm_search_kit.examples.beasyapp_backend.smoke
```

Sortie attendue (8 scénarios, ~5 secondes, gratuit) :

```
[1/8] freetext-search returns scrubbed listings              PASS
[2/8] match-all returns at least one listing                 PASS
[3/8] facets are returned with results                       PASS
[4/8] min/max price filters are respected                    PASS
[5/8] impossible filter returns zero                         PASS
[6/8] price_asc sort is monotonic                            PASS
[7/8] pagination yields disjoint pages                       PASS
[8/8] HTTP error raises BeasyappAPIError                     PASS
All 8 scenarios passed.
```

Si ce smoke passe chez toi, ça veut dire : ngrok up, payload bien
construit, PII bien scrubbée, sort/pagination/facettes OK. Si le
smoke fail, c'est ton backend, pas le kit.

### 2.c. Le leaderboard multi-modèles

Si tu veux choisir quel LLM tu déploies (cher vs pas cher), regarde
[`reports/leaderboard.md`](reports/leaderboard.md). Les **15 mêmes
scénarios** ont été joués sur 6 modèles différents. Tu lis le
tableau, tu prends le moins cher qui passe tout ce qui t'importe.

---

## 3. Branche **TON** LLM (pas besoin de notre gateway)

Le kit parle à **n'importe quel endpoint OpenAI-compatible** — donc
quasiment tous les fournisseurs LLM modernes :

```bash
cp .env.example .env
# Choisis UN bloc et colle-le dans .env :
```

### Option A — OpenAI direct (le plus simple)

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

→ Coût indicatif : ~$0.15 / 1k recherches. Le plus simple, marche partout.

### Option B — Groq (le plus rapide, gratuit jusqu'à un seuil)

```env
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_...
```

→ Gratuit (limites RPM). Tier-list de notre leaderboard : très bon
sur du tool-calling, parfois moins fin sur le français nuancé.

### Option C — OpenRouter (une clé, tous les modèles)

```env
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=anthropic/claude-3.5-sonnet
LLM_API_KEY=sk-or-...
```

→ Tu peux switcher de modèle sans changer ta plomberie, juste
`LLM_MODEL=`. Pratique pour A/B tester en prod.

### Option D — Ollama local (zéro $, sur ta machine ou un serveur GPU)

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=ollama
```

→ Gratuit + offline. Plus lent, qualité dépend du modèle. OK pour dev,
moins pour prod sauf si tu as une bonne GPU.

---

## 4. Commandes pour reproduire les tests chez toi

À copier-coller dans ton terminal après avoir cloné le repo et rempli `.env` :

```bash
git clone https://github.com/JIV-DLS/llm-search-kit.git
cd llm-search-kit
pip install -e ".[dev,flask]"
cp .env.example .env
# édite .env (cf. section 3)

# 1. Smoke adapter (sans LLM, 5s, gratuit)
python -m llm_search_kit.examples.beasyapp_backend.smoke \
    --base-url https://actinolitic-glancingly-saturnina.ngrok-free.dev

# 2. Suite de tests unitaires (mocked LLM, < 1s, gratuit)
pytest -q

# 3. Le scénario qui correspond exactement à ta phrase ("vêtements bébé")
python scripts/run_scenarios.py --only baby_gift \
    --backend-url https://actinolitic-glancingly-saturnina.ngrok-free.dev

# 4. Les 15 scénarios + génération du report card
python scripts/run_scenarios.py \
    --backend-url https://actinolitic-glancingly-saturnina.ngrok-free.dev \
    --out-md docs/REPORT_CARD.md

# 5. (Optionnel) Le leaderboard sur N modèles : passe une liste --models
python scripts/run_scenarios.py --use-stub-backend \
    --models gpt-4o-mini llama-3.3-70b-versatile \
    --out-md reports/leaderboard.md
```

> Dans la commande 5, on utilise un catalogue stub en mémoire pour
> que le leaderboard ne dépende pas de ton ngrok (la qualité de
> l'extraction des filtres dépend du modèle + prompt, pas du catalogue).

---

## 5. Comment intégrer le kit dans Beasyapp

Tu n'as **rien à modifier dans ton backend Spring**. Le kit lance un
petit service Python à côté qui sert `POST /chat` :

```bash
python -m llm_search_kit.examples.beasy_service \
    --beasy-url https://actinolitic-glancingly-saturnina.ngrok-free.dev \
    --port 5000
```

Ton frontend (Flutter / web / mobile) appelle simplement :

```bash
curl -s http://127.0.0.1:5000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"des vêtements doux pour bébé","session_id":"user-123"}' | jq
```

Tu reçois :

```json
{
  "reply": "J'ai trouvé quelques options de vêtements doux et confortables pour bébé...",
  "products": [
    {
      "id": 17,
      "title": "Pyjama bébé à motifs étoiles",
      "price": 3200,
      "images": [...],
      "creator": {"id": 5}    // PII (email/phone/password) déjà retirées
    }
  ],
  "meta": {
    "filters_used": {"query": "vêtements bébé doux confortables"},
    "relaxation_level": 0,
    "model": "gpt-4o-mini"
  }
}
```

Le kit gère :

- la **session** (continuité conversationnelle, "encore moins cher" =
  comprend que tu parles toujours des bébés) ;
- la **relaxation** (si filtres trop stricts → on les enlève un par un
  et on remonte le `relaxation_level` pour que ton front affiche
  "Aucun résultat exact, voici 3 propositions plus larges") ;
- le **PII scrub** au niveau de l'adapter (contrat dur, testé) ;
- les **erreurs HTTP** (timeout, 500 backend) qui remontent comme
  `BeasyappAPIError` au lieu d'une stack trace cryptique.

Détails complets : [`docs/INTEGRATION_BEASY.md`](docs/INTEGRATION_BEASY.md).

---

## 6. Le seul WARN qu'on a vu

Sur 15 scénarios, un seul a renvoyé `WARN` :

| Scénario             | Phrase                                  | Top-1 backend                | Pourquoi WARN                                          |
|----------------------|-----------------------------------------|------------------------------|--------------------------------------------------------|
| `impossible_query`   | `find me a Lamborghini Aventador in Lomé` | `Range Rover Evoque S`      | Ton moteur Spring a renvoyé 10 résultats fuzzy au lieu de 0. |

Ce n'est **pas un bug du kit** : le LLM a correctement extrait
`{query: "Lamborghini Aventador", city: "Lomé"}`. C'est ton matcher
côté Spring qui considère "Range Rover" comme un match raisonnable.

**Action côté toi (optionnelle)** : si tu veux que des requêtes
clairement absurdes renvoient 0 résultats au lieu d'un fallback fuzzy,
ajoute un `min_score` ou un `match_phrase` Elasticsearch dans ton
`AdvancedSearchService`. Mais 99% des vrais utilisateurs ne tapent
pas des trucs absurdes, donc tu peux laisser comme ça en V1.

---

## TL;DR (à coller dans Slack à ton équipe)

> On a un kit Python qui transforme une phrase utilisateur en appel
> à notre `POST /api/v1/listings/search` existant. 14/15 scénarios
> end-to-end PASS sur notre backend (le rapport est ici :
> `github.com/JIV-DLS/llm-search-kit/blob/main/docs/REPORT_CARD.md`).
> Aucune modif Spring nécessaire. On peut brancher OpenAI / Groq /
> OpenRouter / Ollama via un simple `.env`. Démo en local en 5 min :
> `python -m llm_search_kit.examples.beasy_service --beasy-url <ngrok>`.

---

**Questions, blockers, ou tu veux qu'on pair-programme l'intégration Spring/Flutter ? Ping-moi.**
