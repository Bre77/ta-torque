#!/bin/bash
cd "${0%/*}"
OUTPUT="${1:-ta-torque.spl}"
chmod -R u=rwX,go= *
chmod -R u-x+X *
chmod -R u=rwx,go= *
cd ..
tar -cpzf $OUTPUT --exclude=.* --exclude=package.json --overwrite ta-torque