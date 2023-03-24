#!/usr/bin/env bash

cat "$2"
cat "$3" > /dev/stderr

exit $1
