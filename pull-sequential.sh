#!/bin/bash
# A helper script to pull Docker Compose images one by one.
# This prevents "TLS handshake timeout" errors that occur when Docker 
# tries to open too many parallel connections to Docker Hub.

echo "Extracting image list from docker-compose.yml..."
IMAGES=$(docker compose config | grep 'image:' | awk '{print $2}' | sort | uniq)

echo "Found the following images:"
echo "$IMAGES"
echo "----------------------------------------"

for image in $IMAGES; do
  echo "[*] Pulling $image..."
  docker pull "$image"
done

echo "[+] All images pulled successfully. You can now run 'docker compose up -d'."
