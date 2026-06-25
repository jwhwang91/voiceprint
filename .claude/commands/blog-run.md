Run the blog automation cycle with self-healing for Naver DOM changes.

## Steps

1. Ask the user which stage to run if not specified: `collect`, `fetch`, or `publish`. Default to `publish`.

2. Run the stage: `python main.py <stage>`

3. **If it succeeds:** Report completion and any relevant output. Stop.

4. **If it fails with a selector/DOM error — heal from the LIVE DOM, up to 3 attempts total:**
   - Read the full error/traceback to identify which selector or step failed.
   - **Inspect the live DOM** instead of guessing. Run `python main.py inspect-dom` — a health check that reports which `write`/`login` selectors currently MATCH or MISS against the live Naver page. When publishing inside the app, the embedded Naver view is still sitting on the failed editor page, so `inspect-dom` attaches to that exact state via CDP. (CLI-only, no app: add `--editor` to navigate to the post-write page first — requires a logged-in session.)
   - For each broken (`[MISS]`) selector, find the replacement from the live DOM:
     - `python main.py inspect-dom --text '발행'` (or 저장/제목 등) — find a visible element by its text.
     - `python main.py inspect-dom --list buttons` / `--list editable` / `--list inputs` — enumerate interactive elements with a suggested robust selector each.
     - `python main.py inspect-dom --selector '<css>'` — confirm a candidate matches; `--html '<css>'` — dump outerHTML to understand structure.
   - Use the printed `suggest=` value (project convention: partial class match like `[class*="save_btn"]` to survive hash churn). Update `config/selectors.yaml`, leaving a comment on the changed line explaining what was observed.
   - **Verify before retrying:** re-run `python main.py inspect-dom` and confirm the previously-MISS selectors now show `[OK]`.
   - Retry `python main.py <stage>`. If it still fails on a (different) selector, repeat this heal loop — but **no more than 3 publish attempts total**.

5. **When it succeeds:** Report which selector(s) were broken, what they were changed to, and confirm it's working now. Stop.

6. **If still failing after 3 attempts:** Stop looping. Report which selector(s) are still failing, the `inspect-dom` output, what was tried, and what likely needs manual attention. Wait for user input.

## Notes
- Diagnose from the LIVE DOM (`inspect-dom`), not from guessing the error pattern — verify each fix with `inspect-dom` before retrying.
- Cap at 3 publish attempts per run; report and stop if not healed by then.
- If the error is NOT selector-related (network, login, file not found, captcha), report it as-is without touching `config/selectors.yaml` — `inspect-dom`'s "all selectors matched" line is the tell.
- Playwright errors usually name the failing selector directly — use that to target `inspect-dom`.
