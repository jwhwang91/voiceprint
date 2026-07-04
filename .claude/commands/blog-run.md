Run the blog automation cycle with self-healing for Naver DOM changes.

## Steps

1. Ask the user which stage to run if not specified: `collect`, `fetch`, or `publish`. Default to `publish`.

2. Run the stage: `python main.py <stage>`

3. **If it succeeds:** Report completion and any relevant output. Stop.

4. **If it fails with a selector/DOM error — heal from the LIVE DOM, up to 3 attempts total.** Follow `prompts/self_heal_selector.md` exactly. In short:
   - Read the full error/traceback to identify which selector or step failed.
   - **Inspect the live DOM as JSON** instead of guessing: `python main.py inspect-dom --json` (health check: which `write`/`login` selectors MATCH/MISS). Inside the app, the embedded Naver view is still on the failed editor page, so this attaches via CDP. (CLI-only: add `--editor`.)
   - For each `MISS`, find a replacement from the live DOM: `inspect-dom --json --text '발행'`, `--json --list buttons|editable|inputs`, `--json --selector '<css>'`, `--json --html '<css>'`. Prefer robust selectors (stable `data-*`, visible text, aria-label, then partial class match like `[class*="save_btn"]`). Avoid broad selectors (`div`, `button`, `*`).
   - **Write a patch JSON** (do NOT edit `config/selectors.yaml` or any source). Schema and rules: `prompts/self_heal_selector.md` §3. Then apply it: `python main.py apply-selector-patch --patch /tmp/patch.json` — this writes ONLY to `<workspace>/config/selectors.user.yaml` and logs to `<workspace>/logs/healing-history.jsonl`.
   - **Verify before retrying:** re-run `python main.py inspect-dom --json` and confirm the previously-MISS selectors now show `OK`.
   - Retry `python main.py <stage> --job "<job>" --yes`. Repeat the heal loop, but **no more than 3 publish attempts total**.

5. **When it succeeds:** Report which selector(s) were broken, what they were patched to (and that the patch went to the user override, not core config), and confirm it's working now. Stop.

6. **If still failing after 3 attempts:** Stop looping. Report which selector(s) are still failing, the `inspect-dom --json` summary, the patches tried, the likely cause, and what needs manual attention. Wait for user input.

## Notes
- Diagnose from the LIVE DOM (`inspect-dom --json`), not from guessing — verify each fix with `inspect-dom --json` before retrying.
- Healing writes to `<workspace>/config/selectors.user.yaml` via `apply-selector-patch` — it NEVER edits the bundled `config/selectors.yaml` or source code.
- Cap at 3 publish attempts per run; report and stop if not healed by then.
- If the error is NOT selector-related (network, login, file not found) — or if **CAPTCHA / login / security** appears — do NOT heal selectors. Stop and ask the user to complete it manually in the visible Naver view. Never bypass CAPTCHA or login security. `inspect-dom --json`'s `any_miss: false` is the tell that it's not a selector problem.
- Playwright errors usually name the failing selector directly — use that to target `inspect-dom --json`.
