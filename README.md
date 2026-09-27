<div align="center">

<img src="./frontend/public/media/hero/acropolis-399bc-1280.jpg" alt="The Propylaea steps at dawn, 399 BC" width="100%"/>

# Parthenon

**Sit on the steps. Listen. Then let Athens talk.**

A night in Athens where a philosopher takes the floor, a city of citizens argues over what was said, a Scribe writes down what Athens came to believe, and afterwards you can sit with any of them and ask why.

[projectforty2.ai/parthenon](https://projectforty2.ai/parthenon) · A [Project Forty2](https://projectforty2.ai) piece · Built on [MiroFish](https://github.com/666ghj/MiroFish)

</div>

## The night, in five acts

A gathering begins with a scroll: Socrates' Apology, Plato's cave, Aristotle on the mean, or a modern "arrival" (an AI system testifying at a hearing, a data centre in an old quarry), or a stage you build with the Oracle at Delphi.

| Act | What happens |
| --- | --- |
| **Α΄ The Hearing** | The city takes in the words. Every name in the scroll lights up and takes its place in the Web of Athens. |
| **Β΄ The Gathering** | Citizens are summoned from the crowd, each with a past, a stance and a painted face. |
| **Γ΄ The Agora** | They argue for hours in the Agora and the Stoa. Speech rises over the square; who moved, and when, is kept in a ledger. Finished arguments replay at any speed. |
| **Δ΄ The Chronicle** | The Scribe walks the city afterwards and writes what Athens came to believe, and can film it with a narrator. |
| **Ε΄ The Symposium** | Sit with the Scribe, any citizen, or the one who had the floor. When the city is awake they answer live; after the night, from what they remember of it. |

The home page is one scroll-driven climb up the Propylaea steps, with a time-lapse across twenty-four centuries between 399 BC and 2026. There is a Listen switch for the night's sound and the narrator, and the whole product reads in English and Chinese.

## Run it

Requirements: Node 18+, Python 3.11 with [uv](https://docs.astral.sh/uv/), and one language model.

```bash
npm run setup:all          # frontend and backend dependencies
cp .env.example .env       # then choose a model below
npm run dev                # bridge :5055, backend :5001, frontend http://localhost:3000
```

Choose the model in `.env`:

- **A Grok subscription (SuperGrok / X Premium+)**: `npm run grok:login` signs in once through a local OAuth bridge; no API key. Grok Imagine then paints the citizens' faces, films the Chronicle and gives the narrator and citizens their voices.
- **OpenRouter free models**: set `PARTHENON_UPSTREAM=openrouter` and `OPENROUTER_API_KEY`. The bridge rotates the free models. Faces, film and voices need Grok.
- **Any OpenAI-compatible API** (xAI, OpenAI, Anthropic's compatibility endpoint): point `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL_NAME` at it.

Memory is kept locally in SQLite (`MEMORY_BACKEND=auto`); a Zep Cloud key is optional. Runs, reports and portraits live in `backend/uploads/`, which is never committed.

## What is here

- `frontend/`: Vue 3 + Vite. `src/parthenon/` holds the pure modules (the Web as a night sky, the square, the swarm, sound, the descent, the Oracle, vocabulary), and `src/components/ActShell.vue` is the shell every act stands in.
- `backend/`: Flask. The OASIS simulation, the local memory (`app/memory/`), the Scribe (`app/services/report_agent.py`), the film (`chronicle_film.py`), portraits, the stance ledger, and remembered answers for the Symposium (`symposium_memory.py`).
- `bridge/`: the local OpenAI-compatible bridge to a Grok subscription or OpenRouter.
- `locales/`: every visible word, in English and Chinese.

## Credits and licence

Parthenon is a fork of [MiroFish](https://github.com/666ghj/MiroFish) by 666ghj, whose original README is kept in [docs/MIROFISH.md](docs/MIROFISH.md). The simulation runs on [OASIS](https://github.com/camel-ai/oasis) from CAMEL-AI. The footage, paintings, narration and sound of the night were made with Grok Imagine and Grok voice.

Licensed under the [GNU Affero General Public License v3.0](LICENSE), like MiroFish. If you run a modified Parthenon as a public service, you must offer its source to the people who use it.
