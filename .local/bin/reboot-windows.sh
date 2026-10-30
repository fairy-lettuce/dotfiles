#!/bin/bash

# Reboot to Windows only once.
# Requires NOPASSWD sudoer for the executing user.
set -e
sudo -n /usr/bin/grub-reboot "osprober-efi-CE14-1FBF"
systemctl reboot
