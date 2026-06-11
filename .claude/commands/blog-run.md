Run the blog automation cycle with self-healing for Naver DOM changes.

## Steps

1. Ask the user which stage to run if not specified: `collect`, `fetch`, or `publish`. Default to `publish`.

2. Run the stage: `python main.py <stage>`

3. **If it succeeds:** Report completion and any relevant output. Stop.

4. **If it fails:**
   - Read the full error/traceback to identify which selector or step caused the failure
   - Read `config/selectors.yaml` to see the current selector definitions
   - Infer what Naver likely changed based on the error pattern (e.g., class renamed, element restructured, attribute changed, new modal added)
   - Update `config/selectors.yaml` with the best-guess fix, leaving a comment on the changed line explaining what was observed
   - Retry `python main.py <stage>` once

5. **If the retry succeeds:** Report what selector was broken, what the fix was, and confirm it's working now. Stop.

6. **If the retry also fails:** Do NOT loop further. Report:
   - Which selector(s) are still failing
   - What was already tried
   - What manual inspection is likely needed (e.g., open Naver in DevTools and find the element)
   Stop and wait for user input.

## Notes
- Never guess-and-retry more than once per run — report and stop if the fix didn't work
- If the error is not selector-related (e.g., network error, login failure, file not found), report it as-is without touching `config/selectors.yaml`
- Playwright errors usually name the failing selector directly — use that as the primary signal
