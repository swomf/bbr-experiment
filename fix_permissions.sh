#!/usr/bin/env bash

set -x
fd --no-ignore . --type f results* out* | xargs sudo chmod 0644
fd --no-ignore . --type d results* out* | xargs sudo chmod 0755
fd --no-ignore . results* out* | xargs sudo chown "$(whoami)":"$(whoami)"
set +x
