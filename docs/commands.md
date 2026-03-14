# Alle Files + Dateiname cat

```bash
for file in *; do if [ -f "$file" ]; then echo "Datei: $file"; cat "$file"; echo ""; fi; done
```

```bash
find . -type f | sort | while IFS= read -r file; do
  echo "Datei: ${file#./}"
  cat "$file"
  echo
done
```

# Zeilenzähler

```bash
find ./ \( -path '*/.git' -o -path '*/flux-system' -o -path '*/mibs' \) -prune -o -type f -exec wc -l {} + | awk '{total += $1; count++} END {print "Files: " count; print "Zeilen: " total}'
```