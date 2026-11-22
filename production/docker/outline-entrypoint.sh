#!/bin/sh
set -eu
# Outline's startup performs migrations under its own distributed migration lock.
exec node build/server/index.js
