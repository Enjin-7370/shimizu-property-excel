#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
pub=$(mktemp)
trap 'rm -f "$pub"' EXIT
cat >"$pub" <<'PUBLIC_KEY'
-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAzGCqNGNKLnPrjq6VrBBd
pwFi9ukuB4aCuOZZsS4Bz6RPGliq4iz741gGLygRgZ+gOADRptGcWfOnimLZ/9aT
Xu9z6EwCZpqn0gacIqnsEOomt2OzTh52cPc8kNg8H+A3Z2wgMCdf68JxG0AMXULu
A5W2HgRGb4koFrVlWfzyBFnO8/N0HglvnHooNoXjbPguF27FHL4eSuOy/fo/JJ3W
LGRUHuIziQYBmZ/RTZY/vqWP6eVipNqVSCMzM4xlkKr96egXdIEdBB3kyK5oLclU
HLV9Rlz7IzveZn5I2L8fzsTsuLmFQCSMEcffl+cVqpESklAT5gXW76+r97adkZMC
J2PbiGacqNvWMbtTi+8nChRJKxKdLyhNmQ+CjBXzwnVfEdmCcD/YeSy7vGFr0i4s
vE+ctIysrGNxR7w2s657OUbJAQRDZr/Se7usjp+otJpgOueV3EWiywh7cyXUhgcu
cMd03SP9PAIyBU6ZjKm9i98yoKBjURNOUh12SOsc8jdLAgMBAAE=
-----END PUBLIC KEY-----
PUBLIC_KEY
wrapped=$(gcloud secrets versions access latest --project=enjin-bpr-tools --secret=shimizu-openai-api-key --out-file=/dev/stdout | openssl pkeyutl -encrypt -pubin -inkey "$pub" -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256 | base64 -w0)
printf 'ENJIN-WRAPPED-KEY-v1.e4950234c2f7.%s\n' "$wrapped"
