# Signing key

The `build` workflow signs packages and the repo database with a GPG key. Put
the **public** key here so users can trust it:

```sh
# On the machine that holds the key:
gpg --armor --export <KEYID> > keys/signing.pub
git add keys/signing.pub && git commit -m "Add muir signing public key" && git push
```

The **private** key never lives in the repo — it's a CI secret
(`MUIR_GPG_PRIVATE_KEY`, plus `MUIR_GPG_PASSPHRASE` if the key has one).

## Generating the key (one-time)

Use a **passphraseless** key so CI (and `repo-add`) can sign non-interactively;
its secrecy is the CI secret store. (If you must use a passphrase, also set the
`MUIR_GPG_PASSPHRASE` secret — but `repo-add` db signing won't read it.)

```sh
gpg --batch --passphrase '' \
    --quick-generate-key "muir package signing <you@example.com>" rsa4096 sign never
KEYID=$(gpg --list-secret-keys --with-colons | awk -F: '/^sec:/{print $5; exit}')

# Private key -> CI secret
gpg --armor --export-secret-keys "$KEYID" | gh secret set MUIR_GPG_PRIVATE_KEY
# (if you set a passphrase) gh secret set MUIR_GPG_PASSPHRASE

# Public key -> this directory
gpg --armor --export "$KEYID" > keys/signing.pub
```

## Trusting it on each machine

```sh
sudo pacman-key --add keys/signing.pub          # or: curl the raw URL
sudo pacman-key --lsign-key "$KEYID"
```
