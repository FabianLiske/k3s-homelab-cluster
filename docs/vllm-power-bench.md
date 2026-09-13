# vLLM Power-Limit Benchmark

[`tools/vllm_power_bench.py`](../tools/vllm_power_bench.py) misst, wie die
Inferenz-Leistung von vLLM (`apps/internal/llm/vllm/`, 2x Intel Arc Pro B60
auf `wk-5`) mit dem eingestellten GPU-Power-Limit skaliert. Das Script laeuft
lokal, nicht als Cluster-Workload, und spricht per `kubectl port-forward`
direkt mit dem vLLM-Pod (LiteLLM wird umgangen, um Stoervariablen zu
reduzieren).

Das Messen selbst macht
[`vllm-bench`](https://github.com/vllm-project/vllm-bench) (Rust-CLI des
vLLM-Projekts) - ein einzelnes ~7-MB-Binary ohne Python/Torch/GPU-Abhaengigkeit,
das TTFT, Inter-Token-Latency, End-to-End-Latenz und Tokens/s misst und dabei
ueber die Concurrency-Stufen sweept. `vllm_power_bench.py` ruft es fuer die
kurzen/langen Prompt-Profile auf und markiert jeden Lauf mit dem aktuellen
Power-Limit; `--summary` fasst alle bisherigen Laeufe zu einer Vergleichs-CSV
zusammen.

Das Setzen des Power-Limits selbst ist **kein** Teil dieses Scripts - das
bleibt ein manueller Schritt auf `wk-5` (z. B. per `xpu-smi`; dafuer gibt es
aktuell keine Automatisierung im Repo). Das Script bekommt den Wert nur als
Label fuer die Ergebnisdateien uebergeben. Der Benchmark selbst laeuft
weiterhin auf dem Admin-PC und erreicht vLLM ausschliesslich ueber einen
lokalen `kubectl port-forward` auf `127.0.0.1:8000`.

Jeder Messpunkt wird einzeln ausgefuehrt. Vor und nach ihm prueft das Script
`/health`; bereits ein fehlgeschlagener oder unvollstaendiger Request bricht
den gesamten Lauf ab. Solche Diagnoseergebnisse werden unter
`tools/vllm-power-bench-results/failed/` aufbewahrt, aber niemals in die
Summary aufgenommen.

## Voraussetzungen

- `tools/install-vllm-bench.sh` einmalig ausfuehren (laedt das Binary nach
  `tools/.bin/vllm-bench`, nicht eingecheckt).
- `kubectl` Zugriff auf den Cluster.

## Ablauf

1. Power-Limit auf **beiden** GPUs von `wk-5` manuell setzen und kontrollieren.
   Das Argument `--power-limit` dokumentiert den kontrollierten Wert, setzt
   ihn aber nicht selbst. Fuer eine neue Messreihe zuerst mit 200 W einen
   stabilen Referenzlauf erstellen und danach schrittweise absenken.
2. In einem Terminal: `kubectl port-forward -n svc-llm svc/vllm 8000:8000`
3. Benchmark fuer dieses Power-Limit laufen lassen:
   ```bash
   python3 tools/vllm_power_bench.py --power-limit 150
   ```
   Das deckt die Standard-Szenarien mit kurzen und langen Sonnet-Prompts ab.
   Die Last wird kontrolliert ueber getrennte Messpunkte mit Concurrency
   `1,2,4,8` gesteigert; zwischen ihnen liegen standardmaessig 30 Sekunden
   Pause. Greedy-Decoding (`--temperature 0`) vermeidet Zufallsstreuung und
   isoliert den auf XPU auffaelligen Sampling-Pfad. `--concurrency-levels`,
   `--cooldown-seconds`, `--temperature`, `--scenarios` und die
   `--short-*-len`/`--long-*-len` sind anpassbar. Gueltige Ergebnisse landen
   als JSON unter `tools/vllm-power-bench-results/`.
4. Schritte 1-3 fuer weitere Power-Limits wiederholen. Fuer statistische
   Absicherung denselben Power-Limit-Wert auch mehrfach laufen lassen - der
   Summary-Schritt bildet den Median ueber alle Laeufe mit gleichem
   Power-Limit/Szenario/Concurrency.
5. Vergleich ueber alle bisherigen Laeufe:
   ```bash
   python3 tools/vllm_power_bench.py --summary
   ```
   Druckt eine Tabelle (Tokens/s, TTFT, E2E-Latenz je Power-Limit/Szenario)
   und schreibt sie nach `tools/vllm-power-bench-summary.csv`.

## Cross-Check

Die vLLM-eigenen Prometheus-Histogramme (TTFT, Inter-Token-Latency) sind im
Grafana-Dashboard "LLM" sichtbar und koennen als unabhaengiger Vergleichswert
dienen - das Script fragt sie aber bewusst nicht selbst ab.

## Bekannte Stolpersteine

- Der Sonnet-Datensatz von `vllm-bench` braucht `--sonnet-input-len` >
  `--sonnet-prefix-len` (Default-Prefix 200 Tokens) - sonst schlaegt die
  Prompt-Generierung fehl. Die "short"-Defaults setzen den Prefix deshalb auf
  50 Tokens herunter.
- `vllm-bench` laedt den Qwen3-Tokenizer (`Qwen/Qwen3.8-27B-FP8`) von
  Hugging Face; das braucht beim ersten Lauf Netzwerkzugriff, danach ist er
  lokal gecacht.
- Das Standalone-Repo `vllm-project/vllm-bench` ist archiviert. Sollte das per
  `tools/install-vllm-bench.sh` geladene Release-Binary nicht mehr
  funktionieren, ist der aktuelle Stand jetzt Teil von
  `vllm-project/vllm` unter `rust/src/bench` (per `cargo build --release -p
  vllm-bench` bauen).
- `tools/vllm_power_bench.py --summary` erwartet die von `--metadata
  power_limit_watts=... scenario=...` gesetzten Felder in den Ergebnis-JSONs.
  Falls eine kuenftige `vllm-bench`-Version Metrikfelder umbenennt, die
  Kandidaten-Keys in `METRIC_KEYS` am Anfang des Scripts anpassen.
- `vllm-bench` kann selbst bei HTTP-Fehlern mit Exit-Code 0 enden. Deshalb
  validiert der Wrapper zwingend `completed`, `failed` und `num_prompts` aus
  jeder Ergebnisdatei; der Prozess-Exit-Code allein reicht nicht.
- Die alten Messungen vom 12.09.2026 enthalten EngineCore-Haenger bei
  Concurrency 8 (`RPC call to sample_tokens timed out`) sowohl bei 200 W als
  auch bei 160 W. Die betroffenen partiellen Dateien werden von der Summary
  automatisch uebersprungen und duerfen nicht als TDP-Ergebnis interpretiert
  werden.
