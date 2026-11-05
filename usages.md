# How to run

Run every command from the repo root, with the `zehitomo` conda env active.

```bash
conda activate zehitomo
```

`.env` in the repo root must contain:

```text
GOOGLE_API_KEY=...
GOOGLE_MODEL=gemini-3.6-flash
```

`GOOGLE_MODEL` is optional. Quit Chrome completely (Cmd+Q) before a scrape that uses the same profile folder.

## 1. Log in once

Opens real Google Chrome. Sign in on Zehitomo, quit Chrome, then press ENTER in the terminal.

```bash
python login_profile.py alamin
```

The session is saved under `profiles/alamin/`. Use the same name later.

## 2. Build questionnaire combinations

Reads `sections.json` and writes `combination_creation/options.json`.

```bash
# one service
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事

# continue from the next combination if some are already saved
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事

# wipe that service and start again from combination1
python combination_creation/zehitomo_combination.py --service 電気屋・電気工事 --force
```

## 3. Scrape contractors

```bash
# first combination of one service
python -m app.main alamin --service 電気屋・電気工事 --limit 1

# only combination1 and combination2
python -m app.main alamin --service 電気屋・電気工事 \
  --combination combination1 --combination combination2

# every combination saved for that service
python -m app.main alamin --service 電気屋・電気工事
```

Results are written to `output.json` after each combination. Each key under `combinations_done` is the full combination from `options.json` plus `extracted_contractors`.

Optional flags:

```bash
python -m app.main alamin --service 電気屋・電気工事 --limit 1 \
  --options combination_creation/options.json \
  --output output.json
```
