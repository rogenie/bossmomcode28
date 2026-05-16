#!/bin/bash
set -e
apt-get update -qq
apt-get install -y --no-install-recommends fonts-dejavu-core fontconfig
fc-cache -fv
pip install -r requirements.txt
