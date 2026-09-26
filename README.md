# Applications

Polls Greenhouse, Ashby, and Lever, filters new jobs, asks jev for a yes or no, drafts answers, and records every application.

The decided design is in [docs/job-application-spec.md](docs/job-application-spec.md). The board list is [data/ats-board-directory.csv](data/ats-board-directory.csv) (12,918 boards). The readout is [docs/ats-board-directory.md](docs/ats-board-directory.md).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Paste keys into `.env`. That file stays out of git.

- `TYPESAFE_API_KEY` for jev
- `OPENAI_API_KEY` for drafted answers
- `ANSWER_MODEL` defaults to `gpt-6-luna`

Add `profile.md` and `resume.pdf` at the repo root. Those stay out of git too.

The first build stops at drafts and `data/applications.html`. The browser does not submit until a batch of drafts has been approved.
