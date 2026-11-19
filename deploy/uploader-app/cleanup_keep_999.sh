#!/bin/bash
DIR="/home/Serg/public_html/uploader/files"
MAX_FILES=999

count=$(find "$DIR" -type f | wc -l)
if [ "$count" -le "$MAX_FILES" ]; then
  exit 0
fi

to_remove=$((count - MAX_FILES))
find "$DIR" -type f -printf '%T@ %p\n' | sort -n | head -n "$to_remove" | cut -d' ' -f2- | xargs -r rm -f
