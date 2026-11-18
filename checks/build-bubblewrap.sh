#!/usr/bin/env bash
# Reproduce the upstream source/signature checks used for this component.
set -euo pipefail

readonly TAG='v0.13.1'
readonly COMMIT='362936aea0d5c6e70f7af75d2d44b5a914cb4ba2'
readonly FINGERPRINT='252C6FEA78A69D3BC0AD458A616C5BDC0C29AB04'
readonly ARCHIVE_SHA256='0e85c8702248b8dd64144f594147553650cdd0e4c951690345faace79c217c4d'
readonly REPOSITORY='https://github.com/containers/bubblewrap.git'
readonly ARCHIVE="https://github.com/containers/bubblewrap/releases/download/${TAG}/bubblewrap-0.13.1.tar.xz"

fail() {
    printf '%s\n' "bwrap upstream build: $*" >&2
    exit 1
}

[ "$#" -eq 1 ] || fail 'usage: build-from-upstream.sh OUTPUT_DIRECTORY'
out="$1"
[ ! -e "$out" ] || fail 'OUTPUT_DIRECTORY must not already exist'
for tool in curl git gpg meson sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command is missing: $tool"
done

mkdir -p "$out"
install -d -m 700 "$out/gnupg"
curl -fsSL --retry 2 --connect-timeout 15 \
    "https://keys.openpgp.org/vks/v1/by-keyid/${FINGERPRINT: -16}" \
    -o "$out/signer.asc"
gpg --homedir "$out/gnupg" --batch --import "$out/signer.asc" >/dev/null
[ "$(gpg --homedir "$out/gnupg" --with-colons --list-keys "$FINGERPRINT" | awk -F: '$1 == "fpr" {print $10; exit}')" = "$FINGERPRINT" ] || fail 'unexpected upstream signing-key fingerprint'

git clone --depth=1 --branch "$TAG" "$REPOSITORY" "$out/source"
[ "$(git -C "$out/source" rev-parse HEAD)" = "$COMMIT" ] || fail 'tag commit differs from the reviewed source'
GNUPGHOME="$out/gnupg" git -C "$out/source" tag -v "$TAG" >/dev/null
curl -fL --retry 2 --connect-timeout 15 "$ARCHIVE" -o "$out/bubblewrap-0.13.1.tar.xz"
[ "$(sha256sum "$out/bubblewrap-0.13.1.tar.xz" | awk '{print $1}')" = "$ARCHIVE_SHA256" ] || fail 'official release archive checksum differs'

meson setup "$out/build" "$out/source" --buildtype=release -Dtests=false -Dman=disabled \
    -Dbash_completion=disabled -Dzsh_completion=disabled -Dselinux=disabled
meson compile -C "$out/build" bwrap
[ "$("$out/build/bwrap" --version)" = 'bubblewrap 0.13.1' ] || fail 'built version differs'
sha256sum "$out/build/bwrap"
printf '%s\n' "verified upstream rebuild is at $out/build/bwrap"
