#!/usr/bin/env bash

cat "$(dirname "$(realpath "$0")")"/success-stdout.txt

exit 1
