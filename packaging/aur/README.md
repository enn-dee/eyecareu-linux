# Arch packaging

`PKGBUILD` installs Eye-CareU from a GitHub release tarball, matching what
`install-fedora.sh` does on Fedora: the Python package, the desktop entry, the
icon and the udev rule (under `/usr/lib/udev/rules.d/`).

## Install locally

```bash
cd packaging/aur
makepkg -si
```

`python-pyside6` comes from the distribution, so no heavy build is needed.

## Bump the version

1. Change `pkgver` in `PKGBUILD` (`pkgrel=1` again after a version bump).
2. Recompute the checksum:

   ```bash
   updpkgsums
   ```

3. Refresh the metadata that the AUR requires:

   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```

## Publish to the AUR (optional, manual)

The AUR is a separate git host, so this needs your own AUR account and SSH key:

```bash
git clone ssh://aur@aur.archlinux.org/eyecareu.git aur-eyecareu
cp PKGBUILD .SRCINFO eyecareu.install aur-eyecareu/
cd aur-eyecareu && git add -A && git commit -m "eyecareu 1.0.1" && git push
```
