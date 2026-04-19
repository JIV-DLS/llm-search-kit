# 👋 Pour Armand — tout ce que tu dois savoir, dans un seul fichier

Salut Armand. Ouvre **uniquement ce fichier**. Il contient :

1. Ce que fait `llm-search-kit` exactement (en une phrase).
2. La preuve que ça marche end-to-end contre **ton** backend Spring.
3. Comment brancher **ton propre LLM** (OpenAI, Groq, OpenRouter, ou
   Ollama local — pas besoin de notre gateway interne).
4. Les commandes copier-coller pour reproduire chaque test chez toi.
5. Comment intégrer le kit dans Beasyapp (HTTP service prêt à l'emploi).
6. Le seul "warning" qu'on a vu et ce qu'il signifie.
7. **Comment ça marche sous le capot** — le tool-calling et la boucle
   agentique, pour ne pas tomber dans le piège *"c'est juste de
   l'extraction de paramètres"*.
8. **Comment ajouter un 2e tool** sans toucher à `soul.md` — séparation
   propre des responsabilités + recette copier-coller (avec un
   exemple complet `list_categories` déjà committé).

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
LLM_MODEL=qwen2.5:1.5b
LLM_API_KEY=
```

→ Gratuit + offline. Plus lent, qualité dépend du modèle. OK pour dev,
moins pour prod sauf si tu as une bonne GPU.

**3 pièges fréquents avec Ollama** (à connaître avant de râler) :

1. **`LLM_API_KEY` peut rester vide.** Le kit détecte automatiquement les
   serveurs locaux (`localhost`, `127.0.0.1`, `*.local`) et ne réclame pas
   de clé. Laisse vraiment vide — pas de placeholder.
2. **N'oublie pas le `/v1`** à la fin de `LLM_BASE_URL`. Sans ça tu tapes
   l'API native d'Ollama (`/api/chat`) et tu reçois `404 page not found`.
3. **llm-search-kit exige le tool-calling.** Beaucoup de modèles Ollama
   répondent `HTTP 400 "<modèle> does not support tools"` :
   - ❌ ne marchent pas : `llama3`, `llama2`, `mistral` (sans suffixe),
     `gemma`, `phi3`, `deepseek-r1`.
   - ✅ marchent : `qwen2.5`, `qwen3`, `llama3.1`, `llama3.2`, `llama3.3`,
     `mistral-nemo`, `mistral-small`, `command-r`, `hermes3`,
     `firefunction`, `smollm2`.
   Si tu utilises un modèle non compatible, le serveur Flask te répond
   maintenant un **HTTP 422 `model_unsupported_tooling`** avec la liste
   ci-dessus dans le `message`, donc tu vois le fix tout de suite (fini
   le `LLM returned no response (iter 1)` qui boucle).

Pour pull un modèle léger qui marche : `ollama pull qwen2.5:1.5b` (~1 GB,
rapide même sur un Mac M1/M2 ; `qwen2.5:7b` si tu as ≥8 GB de RAM libre).

---

## 4. Commandes pour reproduire les tests chez toi

À copier-coller dans ton terminal après avoir cloné le repo et rempli `.env` :

```bash
git clone https://github.com/JIV-DLS/llm-search-kit.git
cd llm-search-kit

# Option A — la classique pip (la plus simple) :
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt    # tout : runtime + tests + flask

# Option B — installation éditable (équivalente, déclarée dans pyproject.toml) :
# pip install -e ".[dev,flask]"

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

> 🛡️ **Mise à jour** (commit `d716be1`) : le kit a maintenant un
> garde-fou côté Python (`max_relaxed_total=50` par défaut dans
> `flask_server`) qui détecte ce cas — quand la relaxation finit par
> "matcher tout le catalogue", on jette le résultat et on renvoie
> `total=0` au lieu de spammer des items hors-sujet. Donc même si
> tu ne touches pas à ton matcher Spring, tu n'auras plus
> *"j'ai demandé une Range Rover et on me propose des montres"*.
> Voir [`tests/test_search_relaxation_runaway.py`](tests/test_search_relaxation_runaway.py)
> pour les 7 cas de régression.

---

## 7. Comment ça marche sous le capot (très court mais important)

Deux choses qui se font souvent mal comprendre, et qui valent le coup
d'être dites clairement :

### 7.a. Le LLM ne fait **pas** "juste extraire des paramètres"

Quand on dit "le LLM extrait le request body qu'on envoie à Spring",
c'est techniquement vrai mais ça **vend court** ce qu'il fait. Une
vraie extraction (regex, NER) marche sur 1 schéma fixe et casse dès
qu'on bouge. Le LLM, lui, fait **5 décisions distinctes à chaque
tour** :

1. **Routing** — *"parmi les N tools que je connais (`search_catalog`,
   `get_user_orders`, `cancel_subscription`, …), lequel matche
   l'intent ?"* — c'est une classification sur tout ton catalogue
   d'outils. Aujourd'hui tu n'en as qu'un, mais demain tu en auras
   plusieurs et **rien ne change côté kit**, c'est le LLM qui choisit.
2. **Respect du JSON Schema** — *"quels champs sont requis, lesquels
   sont optionnels, quels sont les types attendus ?"*. Le LLM doit
   honorer le contrat publié par le `SearchCatalogSkill`.
3. **Mapping sémantique** — *"l'user a dit 'noir' → `color="#000000"`,
   il a dit 'à Lomé' → `city="Lomé"`, il a dit 'pas trop cher' → je
   **n'invente pas** un `max_price` qu'il n'a pas donné"*.
4. **Décision d'omission** — savoir **quand NE PAS** mettre un filtre
   est aussi dur que savoir quand le mettre. C'est précisément ce qui
   distingue un bon modèle (`gpt-4.1-mini` chez Mammouth, qui omet
   bien) d'un mauvais (`qwen2.5:1.5b` en local, qui invente
   `min_price=5000`).
5. **Multi-tour** — après que ton tool a répondu, le LLM décide :
   *"je rappelle le même tool avec d'autres params ? un autre tool ?
   ou je réponds en langage naturel à l'user ?"*. C'est lui qui
   orchestre, pas nous.

C'est pour ça que dans la doc des fournisseurs LLM tu vois la mention
**"function-calling capability"** — c'est précisément ce skill-là
qu'on évalue, pas de la simple extraction.

### 7.b. La boucle agentique (pattern *ReAct*)

Tu avais raison aussi sur l'autre intuition : **on fait bien des
boucles**. Ce n'est pas *"un appel LLM → un appel tool → fin"*. Le
LLM peut rappeler le tool autant de fois qu'il en a besoin pour
peaufiner. Le pseudo-code complet vit dans
[`llm_search_kit/agent/engine.py:67-124`](llm_search_kit/agent/engine.py)
(méthode `AgentEngine.process`) :

```python
for iteration in range(1, self._max_iterations + 1):
    response = await self._llm.chat_completion(messages, tools, ...)
    tool_calls = response["choices"][0]["message"].get("tool_calls") or []
    if tool_calls:
        execute_each_tool_and_append_results(tool_calls, messages)
        continue                       # ← on rebalance au LLM
    return response["choices"][0]["message"]["content"]   # ← réponse finale
```

Concrètement, les 3 cas typiques :

**Cas 1 — 1 tour (le plus fréquent chez toi aujourd'hui)** :

```
User : "des vêtements bébé"
  → LLM : tool_call(search_catalog, {query: "vêtements bébé"})
  → Kit POST /api/v1/listings/search → 12 résultats
  → LLM lit les 12 → "Voici 3 options qui matchent : ..."
```

**Cas 2 — 2 tours (auto-raffinement)** :

```
User : "samsung 4K pas trop cher"
  → LLM : tool_call(search_catalog, {query: "samsung 4K", max_price: 200000})
  → Kit POST → 0 résultat
  → LLM voit 0, décide d'élargir : tool_call(search_catalog, {..., max_price: 350000})
  → Kit POST → 5 résultats
  → LLM : "J'ai dû élargir un peu ton budget, voici ce que j'ai trouvé..."
```

**Cas 3 — Multi-tools (futur, quand tu en auras plusieurs)** :

```
User : "annule ma commande 12345 et recommande-moi quelque chose"
  → LLM : tool_call(cancel_order, {order_id: 12345}) → ok
  → LLM : tool_call(get_user_history, {}) → liste
  → LLM : tool_call(search_catalog, {category: "headphones", brand: "Sony"}) → 3 produits
  → LLM : "Commande annulée. En te basant sur ton historique je te propose..."
```

### Garde-fous de la boucle

- **`max_iterations = 10`** par défaut (constante `DEFAULT_MAX_ITERATIONS`
  dans `engine.py`). Au-delà on coupe et on renvoie *"I'm having
  trouble completing that request. Could you rephrase?"* — ça évite
  qu'un LLM mal calibré boucle à l'infini.
- En pratique sur des recherches produit on est **presque toujours
  à 1-2 tours**. Si tu vois 5+ tours dans tes logs, c'est un signal
  que ton `soul.md` (system prompt) hésite — ping-moi à ce
  moment-là, on regarde ensemble.
- Le `max_relaxed_total` côté `SearchCatalogSkill` (cf. section 6)
  est l'autre garde-fou : il évite que la relaxation des filtres
  finisse par "matcher tout le catalogue" à un tour donné.

### Ce que ça veut dire pour toi quand tu ajouteras un 2e tool

**Aucune modif côté kit.** Tu écris un nouveau `BaseSkill` (interface
dans `llm_search_kit/agent/base_skill.py`), tu le `register_skill()`
sur l'engine, et le LLM saura naviguer entre les deux. Le routing
(décider lequel appeler quand) est entièrement délégué au LLM, c'est
exactement le point fort du tool-calling vs un router codé à la main.

→ La section suivante te montre **exactement** comment, avec un
exemple réel déjà committé.

---

## 8. Ajouter un nouveau tool (sans toucher à `soul.md`)

> *"Est-ce qu'à chaque fois que je veux ajouter une route, je dois
> modifier le `soul.md` ?"* — Non, jamais. Le `soul.md` ne **définit
> aucun tool**. Il définit juste comment l'agent se comporte une fois
> qu'il a des tools à dispo. La déclaration technique d'un tool vit
> dans des fichiers Python séparés.

### 8.a. Séparation des responsabilités (à mémoriser)

Pour le backend Beasy, l'ensemble du wiring vit dans
[`llm_search_kit/examples/beasyapp_backend/`](llm_search_kit/examples/beasyapp_backend/).
Chaque fichier a **un et un seul** rôle :

| Fichier | Couche | Rôle | Quand tu le touches |
|---|---|---|---|
| `schema.py` | **Définition technique du tool `search_catalog`** : nom, paramètres, types, drop_priority pour la relaxation | Quand tu modifies `SearchRequest.java` côté Spring (nouveau champ, type changé, …) |
| `catalog.py` | **Exécution** : transforme `(filters, query)` en `POST /api/v1/listings/search` Spring + scrub PII | Quand le contrat HTTP de Spring change (URL, headers, format de réponse) |
| `categories_skill.py` | **Un autre tool autonome** (`list_categories`) wrappant `GET /api/v1/categories` | Sert de gabarit pour tout nouveau tool que tu ajouteras |
| `soul.md` | **Stratégie / personnalité** uniquement (ton, règles de mapping, anti-hallucination) | Quand tu changes le ton de l'agent, ses règles de comportement, sa langue |
| `examples/beasy_service.py` | **Wire-up** : assemble tout et expose `POST /chat` sur Flask | Quand tu changes le port, l'auth, ou tu ajoutes un nouveau skill au registre |

Le LLM **découvre** chaque tool via `name` + `description` +
`parameters_schema` (3 props que chaque `BaseSkill` expose). Il décide
seul lequel appeler. Le `soul.md` ne mentionne pas les tools — il dit
juste *"appelle un tool quand l'user cherche un produit"* — ce qui
reste vrai quel que soit le nombre de tools que tu as.

### 8.b. Recette : ajouter un tool en 3 étapes

Voici **exactement** ce qu'on a fait pour ajouter `list_categories`
(commit `<HEAD>`). Tu peux copier-coller pour ton prochain tool
(`get_orders`, `track_delivery`, `get_brands`, …).

**Étape 1 — Crée la classe** (un fichier, ~50 lignes) :

```python
from llm_search_kit.agent.base_skill import BaseSkill, SkillResult

class GetOrdersSkill(BaseSkill):
    def __init__(self, base_url: str): ...

    @property
    def name(self) -> str:
        return "get_orders"  # snake_case, verb-y, stable

    @property
    def description(self) -> str:
        # CRITICAL: this sentence is how the LLM decides when to use you
        # vs the other tools. Be specific. Mention what NOT to use it for.
        return (
            "Get the current user's past orders. Call this when the user "
            "asks 'where is my order?', 'show my purchases', etc. Do NOT "
            "use this for product browsing — use search_catalog instead."
        )

    @property
    def parameters_schema(self) -> dict:
        # JSON Schema. Keep it minimal — every extra param is one more
        # thing the LLM can hallucinate.
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "shipped", "delivered", "cancelled"],
                    "description": "Filter by order status (optional).",
                },
                "limit": {"type": "integer", "description": "Max orders (default 20)."},
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> SkillResult:
        kwargs.pop("__context__", None)  # always strip this
        # ... HTTP call to GET /api/v1/orders ...
        return SkillResult(success=True, data={...}, message="...")
```

Le gabarit complet (avec la couche HTTP, le cleanup, les error paths,
et 10 tests unitaires) vit dans
[`categories_skill.py`](llm_search_kit/examples/beasyapp_backend/categories_skill.py)
et [`tests/test_categories_skill.py`](tests/test_categories_skill.py).

**Étape 2 — Enregistre-le sur l'engine** (1 ligne) :

```python
engine.register_skill(GetOrdersSkill(base_url="https://ton-spring"))
```

Pour le `beasy_service`, on a fait encore plus simple : on a ajouté
un paramètre `enable_categories_skill: bool = True` à `make_app(...)`
(voir
[`beasy_service.py`](llm_search_kit/examples/beasy_service.py)).
Donc pour activer/désactiver le tool depuis la CLI, c'est :

```bash
# active (par défaut)
python -m llm_search_kit.examples.beasy_service --beasy-url https://...

# désactive (si ton Spring n'a pas /categories)
python -m llm_search_kit.examples.beasy_service --beasy-url https://... --no-categories-skill
```

**Étape 3 — C'est tout.** Tu ne touches PAS au `soul.md`. Tu lances
ton serveur. Le LLM verra automatiquement `list_categories` dans la
liste des tools disponibles, lira sa `description`, et décidera tout
seul quand l'appeler. Démo réelle (testé contre Mammouth
`gpt-4.1-nano`) :

```
USER:    "What categories of products do you sell?"
  → tool: list_categories({})
  → reply: "We sell products in the categories of Electronics, Fashion, Baby, and Home."

USER:    "Show me a samsung 4K TV"
  → tool: search_catalog({"query": "Samsung 4K TV"})
  → reply: "I found a Samsung 4K TV available for 180,000 FCFA..."

USER:    "Quels rayons avez-vous ?"   (FR — jamais cité dans le code !)
  → tool: list_categories({})
  → reply: "Nous avons les rayons suivants : Électronique, Mode, Bébé et Maison."
```

→ Le routing entre les 2 tools est **purement** émergent depuis le
`description` que tu écris. Aucun `if`, aucune règle hard-codée.

### 8.c. La piste qui t'intéresse vraiment : génération depuis Swagger

Tu as eu la bonne intuition : **oui, on peut générer `schema.py`
automatiquement depuis ton OpenAPI/Swagger**. Ton Spring expose
`/v3/api-docs` (springdoc-openapi) qui contient déjà le schéma JSON
de `SearchRequest` — il y a une bijection presque parfaite avec
notre `SearchSchema`.

Ce qui se mappe automatiquement (~95% du fichier `schema.py`) :

| Côté Spring (OpenAPI) | Côté kit (`SearchSchema`) |
|---|---|
| `SearchRequest.maxPrice : double` | `SearchField(name="max_price", json_type="number")` |
| `SearchRequest.deliveryType : enum` | `SearchField(..., enum=[...])` |
| `@Schema(description="...")` | `SearchField(..., description="...")` |
| `categoryIds : List<Long>` | `SearchField(..., json_type="array", item_type="integer")` |

Ce qui reste manuel (3 décisions business que l'OpenAPI ne contient pas) :

| Donnée | Pourquoi pas auto | Solution propre |
|---|---|---|
| `drop_priority` (ordre de relaxation) | C'est une décision UX : "quand 0 résultat, lâcher quel filtre en premier ?" | Annoter via OpenAPI extension `x-llm-drop-priority: 5` côté Spring (supporté par springdoc, ne casse rien) |
| `core_keys` (jamais drop) | Décision business : ex. ne jamais drop la `category` | Annotation `x-llm-core: true` |
| `description` orientée LLM | Les `@Schema` Swagger sont rédigées pour les devs Java, pas pour un LLM. *"Maximum price"* vs *"Maximum price in FCFA. Only set when the user gave a number explicitly."* | Annotation `x-llm-description: "..."` qui surcharge la `description` standard |

**Si tu veux que je code ce générateur** (`openapi_to_skill`,
~200 lignes Python + tests), pingue-moi. Pour l'instant on attend que
tu aies réellement besoin de scaler à 5+ tools / 30+ champs avant
d'investir là-dedans — sur ton volume actuel, le `schema.py` à la
main reste plus court à maintenir qu'un générateur.

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
