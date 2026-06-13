#!/usr/bin/env bash
# Configure a fresh fork. Derives owner/repo from the `origin` git remote and
# fills the few spots that need concrete values. Safe to re-run (idempotent).
#
#   ./bootstrap.sh
set -euo pipefail

remote=$(git remote get-url origin 2>/dev/null) || {
  echo "error: no 'origin' remote — clone your fork first" >&2; exit 1
}

# git@github.com:owner/repo.git | https://github.com/owner/repo(.git) -> owner/repo
slug=$(printf '%s' "$remote" | sed -E 's#(git@|https://|ssh://git@)([^/:]+)[/:]##; s#\.git$##')
owner=${slug%%/*}
repo=${slug##*/}
[ -n "$owner" ] && [ -n "$repo" ] && [ "$owner" != "$repo" ] || {
  echo "error: could not parse owner/repo from '$remote'" >&2; exit 1
}
echo "Configuring for: $owner/$repo"

# 1. CODEOWNERS — point the catch-all at the fork owner (keeps any comments).
if [ -f CODEOWNERS ] && grep -qE '^\* @' CODEOWNERS; then
  sed -i -E "s|^\* @.*|* @$owner|" CODEOWNERS
else
  printf '* @%s\n' "$owner" > CODEOWNERS
fi

# 2. Terraform variables.
cat > terraform/terraform.tfvars <<EOF
github_owner    = "$owner"
repository_name = "$repo"
EOF

# 3. Pacman repo stanza (for /etc/pacman.conf).
sed -e "s/@OWNER@/$owner/g" -e "s/@REPO@/$repo/g" \
    contrib/pacman-repo.conf.in > contrib/pacman-repo.conf

cat <<EOF

Wrote:
  CODEOWNERS                    -> * @$owner
  terraform/terraform.tfvars    -> $owner / $repo
  contrib/pacman-repo.conf      -> [$repo] @ github.com/$owner/$repo

Next steps:
  1. Signing key (see keys/README.md):
       gpg --armor --export-secret-keys \$KEYID | gh secret set MUIR_GPG_PRIVATE_KEY
       gpg --armor --export \$KEYID > keys/signing.pub
  2. gh secret set MUIR_PR_TOKEN          # PAT so sync PRs trigger CI
     gh secret set OPENROUTER_API_KEY     # or CLAUDE_CODE_OAUTH_TOKEN
  3. cd terraform && terraform init && terraform import github_repository.this $repo && terraform apply
  4. python tools/sync.py --from-installed     # seed from this machine, then commit + push
  5. sudo pacman-key --add keys/signing.pub && sudo pacman-key --lsign-key \$KEYID
     cat contrib/pacman-repo.conf | sudo tee -a /etc/pacman.conf
EOF
