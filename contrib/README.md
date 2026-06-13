# contrib — keeping the mirror in sync with this machine

CI detects **updates** to packages already mirrored. Discovering packages you've
**installed** must happen on your Arch box (only it knows `pacman -Qmq`). These
helpers automate that.

## One-time seed

From a local clone of the repo, on the machine with your AUR packages:

```sh
# Preview which installed AUR packages would be tracked:
python tools/sync.py --from-installed --dry-run

# Materialize them into the working tree, then commit + push:
python tools/sync.py --from-installed
git add -A && git commit -m "Seed mirror from installed AUR packages"
git push
```

`--from-installed` reads `pacman -Qmq`, resolves each to its AUR `pkgbase`
(so split packages collapse to one entry), skips anything not on the AUR, and
tracks only the ones not already mirrored.

## Ongoing: pick up newly-installed packages

After the seed, run discovery on a schedule so new installs get mirrored as
**audited PRs** (`--open-prs` opens one "Add <pkg>" PR per new package).

### systemd user timer (recommended)

```sh
# Make the wrapper executable and adjust MUIR_REPO if your clone isn't ~/src/muir
chmod +x contrib/muir-sync-installed

cp contrib/muir-sync.service contrib/muir-sync.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now muir-sync.timer
```

Runs daily as you (your `gh`/ssh credentials). `systemctl --user start
muir-sync.service` runs it on demand.

### Optional: trigger on install (pacman hook)

For near-instant discovery instead of waiting for the timer, install
`muir-discover.hook` to `/etc/pacman.d/hooks/` (edit `YOURUSER`). It only nudges
the user service — the git/gh work still runs as you. Run
`loginctl enable-linger YOURUSER` so the user service is reachable from the
root-run hook. See the comments in the hook file.

## Why PRs for new packages?

A first import is a 100%-new PKGBUILD, so triage flags it high-risk and the LLM
audit reviews it before it merges — exactly the supply-chain gate you want when
pulling a package into the mirror for the first time.
