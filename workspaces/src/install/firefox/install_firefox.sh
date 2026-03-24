#!/usr/bin/env bash
set -xe

# Trimmed down version of KASM's own firefox install script (the full onw is
# quite verbose!)

# Add icon
if [[ -f /dockerstartup/install/firefox/firefox/firefox.desktop ]]; then
  mv /dockerstartup/install/firefox/firefox.desktop "${HOME}"/Desktop/
fi

# Prefer TARGETARCH (set by Docker Buildx); fallback to system uname -m
# Convert to GNU triplet format for library paths
src_arch="${TARGETARCH:-$(uname -m)}"

case "${src_arch}" in
  amd64|x86_64)
    GNU_ARCH="x86_64"
    ;;
  arm64|aarch64)
    GNU_ARCH="aarch64"
    ;;
  386)
    GNU_ARCH="i386"
    ;;
  *)
    GNU_ARCH="${src_arch}"
    ;;
esac

echo "Install Firefox"
if [[ ! -f '/etc/apt/preferences.d/mozilla-firefox' ]]; then
  add-apt-repository -y ppa:mozillateam/ppa
  echo '
Package: *
Pin: release o=LP-PPA-mozillateam
Pin-Priority: 1001
' > /etc/apt/preferences.d/mozilla-firefox
fi
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::ForceIPv4=true firefox p11-kit-modules

# Update firefox to utilize the system certificate store instead of the one that ships with firefox
rm -f /usr/lib/firefox/libnssckbi.so
ln /usr/lib/"${GNU_ARCH}"-linux-gnu/pkcs11/p11-kit-trust.so /usr/lib/firefox/libnssckbi.so

preferences_file=/usr/lib/firefox/browser/defaults/preferences/firefox.js

# Disabling default first run URL for Debian based images
cat >"${preferences_file}" <<EOF
pref("datareporting.policy.firstRunURL", "");
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("datareporting.healthreport.service.enabled", false);
pref("datareporting.healthreport.uploadEnabled", false);
pref("trailhead.firstrun.branches", "nofirstrun-empty");
pref("browser.aboutwelcome.enabled", false);
EOF

# Creating Default Profile
chown -R 0:0 "${HOME}"
firefox -headless -CreateProfile "kasm ${HOME}/.mozilla/firefox/kasm"

# Silence Firefox security nag "Some of Firefox's features may offer less protection on your current operating system".
echo 'user_pref("security.sandbox.warn_unprivileged_namespaces", false);' > "${HOME}"/.mozilla/firefox/kasm/user.js
chown 1000:1000 "${HOME}"/.mozilla/firefox/kasm/user.js

# configure smartcard support
# note: some firefox versions don't read from the global pkcs11.txt when creating profiles
if [[ ${KASM_SVC_SMARTCARD:-1} == 1 ]] && [[ -f "${HOME}/.pki/nssdb/pkcs11.txt" ]]; then
    cp "${HOME}"/.pki/nssdb/pkcs11.txt "${HOME}"/.mozilla/firefox/kasm/pkcs11.txt
    chown 1000:1000 "${HOME}"/.mozilla/firefox/kasm/pkcs11.txt
fi

# Starting with version 67, Firefox creates a unique profile mapping per installation which is hash generated
#   based off the installation path. Because that path will be static for our deployments we can assume the hash
#   and thus assign our profile to the default for the installation
cat >>"${HOME}"/.mozilla/firefox/profiles.ini <<EOL
[Install4F96D1932A9F858E]
Default=kasm
Locked=1
EOL

# Cleanup for app layer
chown -R 1000:0 "${HOME}"
find /usr/share/ -name "icon-theme.cache" -exec rm -f {} \;
if [[ -f "${HOME}"/Desktop/firefox.desktop ]]; then
  chmod +x "${HOME}"/Desktop/firefox.desktop
fi
chown -R 1000:1000 "${HOME}"/.mozilla