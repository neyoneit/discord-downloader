#!/usr/bin/env bash
# safety settings
set -u
set -e
set -o pipefail


if [ $# != 2 ]; then
  echo 'bad arg count'
  exit 1
fi
if [ "$1" != "+exec" ]; then
  echo "bad first arg"
  exit 1
fi

dn=$(dirname "$(realpath "$0")")/..
cat $dn/config/$2
touch $dn/video/$(basename $2 .cfg | sed 's/^file-//').mp4
