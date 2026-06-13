# The muir bot — a GitHub App

The bot is a **GitHub App** so that (1) the PRs it opens trigger CI (the default
`GITHUB_TOKEN` doesn't), and (2) it can be a **ruleset bypass actor** — letting
its audit-clean update PRs auto-merge while every human PR still needs your
code-owner review.

## Create it (one-time, ~3 min)

1. **github.com → Settings → Developer settings → GitHub Apps → New GitHub App.**
2. Permissions (Repository):
   - **Contents: Read and write**
   - **Pull requests: Read and write**
   - Metadata: Read (automatic)
3. "Where can this be installed?" → **Only on this account.** Create.
4. Note the **App ID** (shown on the app page).
5. **Generate a private key** → downloads a `.pem`.
6. **Install App** → select your `muir` repo.

## Wire it up

```sh
gh secret set MUIR_APP_ID --body "<APP_ID>"
gh secret set MUIR_APP_PRIVATE_KEY < /path/to/key.pem
```

Then make it the ruleset bypass actor so its PRs auto-merge:

```sh
# terraform/terraform.tfvars
bot_app_id = <APP_ID>
```
`terraform apply`.

That's it. `sync.yml` automatically uses the App token when `MUIR_APP_ID` is set
(falling back to `MUIR_PR_TOKEN`/`GITHUB_TOKEN` until then). Once `bot_app_id`
is applied, the bot's vetted PRs auto-merge and human PRs wait for you.

> Until the App exists, the ruleset requires a review on **every** PR (including
> the bot's), so nothing auto-merges. That's the safe default.
