#!/bin/bash
set -e

# Paths
DB_PATH="./backend/data"
DB_BACKUP_PATH="../.backups/openwebui"

# Timestamp
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"

# Create backup directory
mkdir -p "$DB_BACKUP_PATH"

tar czf "$DB_BACKUP_PATH/openwebui-data-$TIMESTAMP.tar.gz" \
    -C "$DB_PATH" .

echo "Backup completed:"
echo "$DB_BACKUP_PATH/openwebui-data-$TIMESTAMP.tar.gz"

# To restore, essentially delete existing databse and untar the tar file into the data directory