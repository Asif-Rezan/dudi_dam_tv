#!/usr/bin/env bash
# Avoid slow runner mirror selection and bound all package network operations.
set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo 'Usage: install-runner-packages.sh PACKAGE ...' >&2
  exit 2
fi

missing=()
for package in "$@"; do
  if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" != 'install ok installed' ]]; then
    missing+=("$package")
  fi
done
if [[ ${#missing[@]} -eq 0 ]]; then
  echo 'Required runner packages are already installed; skipping apt.'
  exit 0
fi

# Ubuntu 24.04 uses deb822 .sources; also support legacy .list files.
# Replace mirror-list URIs as well as direct Azure URLs so index requests and
# package downloads both use the official HTTPS archive.
while IFS= read -r -d '' source; do
  sudo sed -i -E \
    -e 's|mirror\+file:/+etc/apt/apt-mirrors.txt|https://archive.ubuntu.com/ubuntu|g' \
    -e 's|mirror\+file:/+etc/apt/apt-mirrors-security.txt|https://security.ubuntu.com/ubuntu|g' \
    -e 's|https?://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' \
    "$source"
done < <(find /etc/apt -type f \( -name '*.list' -o -name '*.sources' \) -print0)

apt_options=(
  -o Acquire::Retries=2
  -o Acquire::http::Timeout=20
  -o Acquire::https::Timeout=20
)
# Hosted runner images often already contain usable package indexes. Avoid a
# costly global refresh when the requested packages can be installed directly.
install_packages() {
  sudo env DEBIAN_FRONTEND=noninteractive timeout --kill-after=15s 300s \
    apt-get "${apt_options[@]}" install -y --no-install-recommends "${missing[@]}"
}
if install_packages; then
  exit 0
fi

# Only Ubuntu repositories are needed for these OS media tools. Avoid refreshing
# unrelated Microsoft/Docker/etc. repositories, without deleting their config.
index_sources=''
if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
  index_sources="$(mktemp -d)"
  trap 'rm -rf "$index_sources"' EXIT
  chmod 755 "$index_sources"
  cp /etc/apt/sources.list.d/ubuntu.sources "$index_sources/ubuntu.sources"
  chmod 644 "$index_sources/ubuntu.sources"
  apt_options+=(-o Dir::Etc::sourcelist=/dev/null -o "Dir::Etc::sourceparts=$index_sources")
fi
apt_options+=(-o Acquire::Languages=none)
for attempt in 1 2; do
  echo "Refreshing Ubuntu package indexes (attempt $attempt/2)"
  if sudo timeout --kill-after=15s 240s apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update; then
    if install_packages; then
      exit 0
    fi
  fi
  echo "Package refresh/install attempt $attempt failed; preserving diagnostics."
done
echo 'Unable to install required media tools after bounded recovery attempts.' >&2
exit 1
