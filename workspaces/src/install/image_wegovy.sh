#!/usr/bin/env bash
set -e

# Configure locale generation to only build en_US.UTF-8 to reduce build time
echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    rm -rf /var/lib/locales/supported.d/*

apt-get update -y \
    && apt-get remove -y gnome* --purge --no-install-recommends \
    && apt-get autoremove -y

rm -Rf ${STARTUPDIR}/audio_input
rm -Rf ${STARTUPDIR}/gamepad
rm -Rf ${STARTUPDIR}/jsmpeg
rm -Rf ${STARTUPDIR}/printer
rm -Rf ${STARTUPDIR}/recorder
rm -Rf ${STARTUPDIR}/smartcard
rm -Rf ${STARTUPDIR}/upload_server
rm -Rf ${STARTUPDIR}/webcam

# Remove Noto fonts to save space. These are very large and we don't use them.
rm -rf /usr/share/fonts/opentype/noto
rm -rf /usr/share/fonts/truetype/noto

# Remove unneeded locale files to save space. We only need English.
shopt -s extglob
rm -rf /usr/share/locale-langpack/!(en)
rm -rf /usr/share/locale/!(en)
rm /usr/lib/locale/locale-archive
localedef -i en_US -f UTF-8 en_US.UTF-8

# Remove unneeded icons to save space. These are large and we don't use them.
rm -rf /usr/share/icons/capitaine-cursors
rm -rf /usr/share/icons/Humanity
rm -rf /usr/share/icons/Humanity-Dark
rm -rf /usr/share/icons/Adwaita
rm -rf /usr/share/doc/adwaita-icon-theme
rm -rf /usr/share/icons/Tango
rm -rf /usr/share/icons/ubuntu-mono-light
rm -rf /usr/share/icons/ubuntu-mono-dark
rm -rf /usr/share/icons/LoginIcons

# Removing the fancy bloated backgrounds that came with kasm and ubuntu
mv /usr/share/backgrounds/xfce /usr/share/backgrounds.cpy
rm -rf /usr/share/backgrounds
mv /usr/share/backgrounds.cpy /usr/share/backgrounds

# Remove packages we don't need anymore to save space.
apt-get autoremove -y --purge --no-install-recommends \
    desktop-base \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    vim \
    cups

# Remove cups files
rm -rf /usr/lib/cups
rm -rf /usr/share/cups
rm -rf /etc/cups
rm -rf /etc/cupshelpers
