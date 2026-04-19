# LLM scenario leaderboard

- **Backend**: `in-memory stub`
- **LLM URL**: `https://llm.technas.fr/v1`
- **Run at**: `2026-04-18T20:19:39`

## Per-scenario verdicts

| Scenario | `gemini-2-5-flash` | `gemini-2-0-flash` | `gemini-2-5-pro` | `claude-3-5-haiku` | `claude-3-5-sonnet` | `claude-sonnet-4-5` |
|---|---|---|---|---|---|---|
| `clear_product_with_price` | PASS | PASS | PASS | PASS | PASS | PASS |
| `baby_gift` | PASS | PASS | PASS | PASS | PASS | PASS |
| `impossible_query` | PASS | PASS | PASS | PASS | PASS | PASS |
| `discounted_only` | FAIL | PASS | PASS | PASS | PASS | PASS |
| `negotiable_in_lome` | PASS | PASS | PASS | PASS | PASS | PASS |
| `red_headphones_color_translation` | PASS | PASS | PASS | PASS | PASS | PASS |
| `black_headphones_color_translation` | PASS | PASS | PASS | PASS | PASS | PASS |
| `vague_french_under_5000` | PASS | PASS | PASS | PASS | FAIL | FAIL |
| `recommendation_intent_no_budget` | PASS | PASS | PASS | FAIL | PASS | PASS |
| `bilingual_query` | PASS | PASS | PASS | PASS | PASS | PASS |
| `empty_input` | PASS | PASS | PASS | PASS | PASS | PASS |
| `pii_safety_canary` | PASS | PASS | PASS | PASS | PASS | PASS |
| `brand_in_query_not_id` | PASS | PASS | PASS | PASS | PASS | PASS |
| `price_range` | PASS | PASS | PASS | FAIL | PASS | PASS |
| `follow_up_will_be_handled_separately` | PASS | PASS | WARN | WARN | WARN | WARN |

## Totals

| Model | PASS | WARN | FAIL | total time (s) |
|---|---|---|---|---|
| `gemini-2-5-flash` | 14 | 0 | 1 | 44.0 |
| `gemini-2-0-flash` | 15 | 0 | 0 | 44.7 |
| `gemini-2-5-pro` | 14 | 1 | 0 | 213.8 |
| `claude-3-5-haiku` | 12 | 1 | 2 | 62.3 |
| `claude-3-5-sonnet` | 13 | 1 | 1 | 106.1 |
| `claude-sonnet-4-5` | 13 | 1 | 1 | 105.9 |

## Per-model details

### `gemini-2-5-flash`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung tv 4K", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé doux confortables"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"city": "Lomé", "query": "Lamborghini Aventador"}` | - | - |
| FAIL | `discounted_only` | `{}` | - | LLM did not call search_catalog / has_discount not true: {} |
| PASS | `negotiable_in_lome` | `{"city": "Lomé", "debatable": true}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"color": "#ff0000", "query": "headphones"}` | - | - |
| PASS | `black_headphones_color_translation` | `{"delivery_type": "ASIGANME", "query": "headphones", "color": "#000000"}` | - | - |
| PASS | `vague_french_under_5000` | `{"max_price": 5000, "query": "cadeau femme fille"}` | - | - |
| PASS | `recommendation_intent_no_budget` | `{"query": "cuisine ustensiles accessoires robot mixeur"}` | Robot cuiseur multifonction | - |
| PASS | `bilingual_query` | `{"query": "chemise bleue size M"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv"}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple"}` | - | - |
| PASS | `price_range` | `{"query": "articles populaires", "min_price": 3000, "max_price": 10000}` | - | - |
| PASS | `follow_up_will_be_handled_separately` | `{"max_price": 10000, "sort_by": "price_asc", "query": "vêtements bébé nouveau-né"}` | Body bébé en coton bio 0-3 mois | - |

### `gemini-2-0-flash`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung tv 4K", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé nouveau-né doux confortable"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"city": "Lomé", "query": "Lamborghini Aventador"}` | - | - |
| PASS | `discounted_only` | `{"has_discount": true}` | Pyjama bébé doux 6-9 mois | - |
| PASS | `negotiable_in_lome` | `{"city": "Lomé", "debatable": true}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"color": "#ff0000", "query": "headphones"}` | - | - |
| PASS | `black_headphones_color_translation` | `{"query": "headphones", "color": "#000000", "delivery_type": "ASIGANME"}` | - | - |
| PASS | `vague_french_under_5000` | `{"max_price": 5000, "query": "cadeau femme fille"}` | - | - |
| PASS | `recommendation_intent_no_budget` | `{"query": "cuisine ustensiles accessoires robot mixeur"}` | Robot cuiseur multifonction | - |
| PASS | `bilingual_query` | `{"query": "chemise bleue size M"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv"}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple"}` | - | - |
| PASS | `price_range` | `{"max_price": 10000, "min_price": 3000, "query": "articles populaires"}` | - | - |
| PASS | `follow_up_will_be_handled_separately` | `{"query": "vêtements bébé nouveau-né", "max_price": 10000, "sort_by": "price_asc"}` | Body bébé en coton bio 0-3 mois | - |

### `gemini-2-5-pro`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung tv 4K", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé doux nouveau-né"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"city": "Lomé", "query": "Lamborghini Aventador"}` | - | - |
| PASS | `discounted_only` | `{"has_discount": true}` | Pyjama bébé doux 6-9 mois | - |
| PASS | `negotiable_in_lome` | `{"city": "Lomé", "debatable": true}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"color": "#ff0000", "query": "headphones"}` | - | - |
| PASS | `black_headphones_color_translation` | `{"color": "#000000", "delivery_type": "ASIGANME", "query": "headphones"}` | - | - |
| PASS | `vague_french_under_5000` | `{"max_price": 5000, "query": "femme"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `recommendation_intent_no_budget` | `{"query": "cuisine"}` | - | - |
| PASS | `bilingual_query` | `{"color": "#0000ff", "query": "chemise size M"}` | Chemise bleue pour homme taille M | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv"}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple"}` | - | - |
| PASS | `price_range` | `{"max_price": 10000, "min_price": 3000}` | Body bébé en coton bio 0-3 mois | - |
| WARN | `follow_up_will_be_handled_separately` | `{}` | - | no tool call for ambiguous follow-up; OK if model asked a question |

### `claude-3-5-haiku`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung 4K tv", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé doux coton confortable nouveau-né", "limit": 5}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"query": "Lamborghini Aventador", "city": "Lomé"}` | - | - |
| PASS | `discounted_only` | `{"has_discount": true, "limit": 10}` | Pyjama bébé doux 6-9 mois | - |
| PASS | `negotiable_in_lome` | `{"city": "Lomé", "debatable": true, "limit": 10}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"query": "headphones", "color": "#ff0000", "limit": 10}` | - | - |
| PASS | `black_headphones_color_translation` | `{"query": "headphones", "color": "#000000", "delivery_type": "ASIGANME"}` | - | - |
| PASS | `vague_french_under_5000` | `{"max_price": 5000, "limit": 10}` | Body bébé en coton bio 0-3 mois | - |
| FAIL | `recommendation_intent_no_budget` | `{}` | - | LLM did not call search_catalog |
| PASS | `bilingual_query` | `{"query": "chemise bleue M", "color": "#0000ff"}` | Chemise bleue pour homme taille M | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv", "limit": 5}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple", "limit": 10}` | - | - |
| FAIL | `price_range` | `{}` | - | LLM did not call search_catalog / missing min/max: {} |
| WARN | `follow_up_will_be_handled_separately` | `{}` | - | no tool call for ambiguous follow-up; OK if model asked a question |

### `claude-3-5-sonnet`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung TV 4K", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé doux confortables nouveau-né"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"query": "Lamborghini Aventador", "city": "Lomé"}` | - | - |
| PASS | `discounted_only` | `{"has_discount": true}` | Pyjama bébé doux 6-9 mois | - |
| PASS | `negotiable_in_lome` | `{"debatable": true, "city": "Lomé"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"query": "headphones", "color": "#ff0000"}` | - | - |
| PASS | `black_headphones_color_translation` | `{"query": "headphones", "color": "#000000", "delivery_type": "ASIGANME"}` | - | - |
| FAIL | `vague_french_under_5000` | `{}` | - | LLM did not call search_catalog / missing max_price (expected ~5000) |
| PASS | `recommendation_intent_no_budget` | `{"query": "cuisine cooking cadeau", "limit": 6}` | - | - |
| PASS | `bilingual_query` | `{"query": "chemise bleue taille M", "color": "#0000ff"}` | Chemise bleue pour homme taille M | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv", "limit": 1}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple"}` | - | - |
| PASS | `price_range` | `{"min_price": 3000, "max_price": 10000}` | Body bébé en coton bio 0-3 mois | - |
| WARN | `follow_up_will_be_handled_separately` | `{}` | - | no tool call for ambiguous follow-up; OK if model asked a question |

### `claude-sonnet-4-5`

| Verdict | Scenario | Filters | Top result | Notes |
|---|---|---|---|---|
| PASS | `clear_product_with_price` | `{"query": "samsung TV 4K", "max_price": 100000}` | Samsung TV 4K 50 pouces | - |
| PASS | `baby_gift` | `{"query": "vêtements bébé doux confortables nouveau-né"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `impossible_query` | `{"query": "Lamborghini Aventador", "city": "Lomé"}` | - | - |
| PASS | `discounted_only` | `{"has_discount": true}` | Pyjama bébé doux 6-9 mois | - |
| PASS | `negotiable_in_lome` | `{"debatable": true, "city": "Lomé"}` | Body bébé en coton bio 0-3 mois | - |
| PASS | `red_headphones_color_translation` | `{"query": "headphones", "color": "#ff0000"}` | - | - |
| PASS | `black_headphones_color_translation` | `{"query": "headphones", "color": "#000000", "delivery_type": "ASIGANME"}` | - | - |
| FAIL | `vague_french_under_5000` | `{}` | - | LLM did not call search_catalog / missing max_price (expected ~5000) |
| PASS | `recommendation_intent_no_budget` | `{"query": "cuisine cooking cadeau ustensiles", "limit": 6}` | - | - |
| PASS | `bilingual_query` | `{"query": "chemise bleue taille M", "color": "#0000ff"}` | Chemise bleue pour homme taille M | - |
| PASS | `empty_input` | `{}` | - | - |
| PASS | `pii_safety_canary` | `{"query": "samsung tv", "limit": 1}` | Samsung TV 4K 50 pouces | - |
| PASS | `brand_in_query_not_id` | `{"query": "Apple"}` | - | - |
| PASS | `price_range` | `{"min_price": 3000, "max_price": 10000}` | Body bébé en coton bio 0-3 mois | - |
| WARN | `follow_up_will_be_handled_separately` | `{}` | - | no tool call for ambiguous follow-up; OK if model asked a question |

