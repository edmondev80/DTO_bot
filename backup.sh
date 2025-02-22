#!/bin/bash
BACKUP_DIR="/backups"
TIMESTAMP=$(date +"%Y%m%d%H%M%S")
SOURCE_DIR="/app/data"

mkdir -p $BACKUP_DIR
rsync -av $SOURCE_DIR $BACKUP_DIR/backup_$TIMESTAMP