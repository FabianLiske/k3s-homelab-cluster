#!/bin/sh
set -e
out=''
skip=0
for arg in "$@"; do
  if [ "$skip" = 1 ]; then
    skip=0
    continue
  fi
  if [ "$arg" = "-L" ]; then
    skip=1
    continue
  fi
  out="$out $(printf "%s" "$arg" | sed "s/'/'\\\\''/g; s/.*/'&'/")"
done
eval exec /usr/sbin/ipmitool -C 3 $out