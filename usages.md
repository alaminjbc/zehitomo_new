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

Results are written to `output.json` after each combination. The file keeps **all services** under `services.<service_name>.combinations_done` (switching service in rotate config does not wipe earlier services). Each combination stores steps, `extracted_contractors`, and the `profile` that ran it. Already-finished combinations are skipped unless you pass `--rerun`. Captcha exits with code `2` and does **not** mark that combination done — rotation scripts retry the same combination on the next profile.

Optional flags:

```bash
python -m app.main alamin --service 電気屋・電気工事 --limit 1 \
  --options combination_creation/options.json \
  --output output.json
```

Finished contractors are also appended to `zehitomo_main.csv`.

## 4. Experiment: profile switching

Edit [`scripts/rotate_config.json`](scripts/rotate_config.json), then run one command. Already-done combinations in `output.json` are skipped.

```json
{
  "mode": "batch",
  "profiles": ["alamin", "azimon"],
  "service": "電気屋・電気工事",
  "options": "combination_creation/options.json",
  "output": "output.json",
  "batch_max": 6,
  "batch_size": 3
}
```

`mode` values:

| mode | meaning |
|---|---|
| `round_robin` | Way-1: each combination uses the next profile |
| `until_captcha` | Way-2: stay on a profile until captcha or `batch_max` |
| `batch` | Way-3: each profile does `batch_size` combos, then rotate |

```bash
# uses mode + settings from rotate_config.json
./scripts/run_rotate.sh

# override mode for one run
MODE=round_robin ./scripts/run_rotate.sh

# optional: another config file
./scripts/run_rotate.sh scripts/rotate_config.json
```

The individual scripts still work and also read the same JSON (CLI profile args override `profiles` if given):

```bash
./scripts/rotate_round_robin.sh
./scripts/rotate_until_captcha.sh
./scripts/rotate_batch.sh
```
