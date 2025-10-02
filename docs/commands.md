# Alle Files + Dateiname cat

```bash
for file in *; do if [ -f "$file" ]; then echo "Datei: $file"; cat "$file"; echo ""; fi; done
```