# Minecraft (Paper) in Pelican aufsetzen

## Zielbild

Ein Minecraft-Server laeuft als Pelican-verwalteter Container auf `media-1`.
Das Server-Backend ist **Paper** – das meistgenutzte Performance-optimierte Minecraft-Backend.
Paper ist vollstaendig Vanilla-kompatibel, aber signifikant schneller und unterstuetzt das gesamte Bukkit/Spigot-Plugin-Oekosystem.

Game-Traffic laeuft wie bei allen Spielservern auf `172.26.50.31` (vlan50).

---

## Voraussetzungen

* Pelican-Panel laeuft intern unter `https://pelican.intern.rohrbom.be`
* Wings ist auf `media-1` aktiv: `sudo systemctl status wings`
* Node `media-1` ist im Panel angelegt und verbunden
* Portforward auf dem Router steht noch aus (kommt in Phase 7)

---

## Warum Paper?

| | Vanilla | Paper | Fabric+Mods |
|---|---|---|---|
| Plugin-Support | nein | ja (Bukkit/Spigot/Paper) | nein |
| Performance vs. Vanilla | – | mittel–hoch | hoch |
| Vanilla-Kompatibilitaet | 100 % | ~99 % | ~99 % |
| Betriebsaufwand | niedrig | niedrig | mittel |

Paper ist der Standardweg fuer einen Server mit Plugin-Support **und** besserer Performance.
Wer ausschliesslich technische Performance-Mods ohne Plugin-Ecosystem will (Lithium, FerriteCore, Krypton etc.), sollte stattdessen das Fabric-Egg verwenden.

---

## Phase 1: Paper-Egg importieren

Pelican verwendet *Eggs* zur Definition von Gameserver-Typen.
Das Paper-Egg kommt aus dem offiziellen Pelican-Eggs-Repository.

### 1. Egg-JSON herunterladen

```bash
curl -O https://raw.githubusercontent.com/pelican-eggs/eggs/master/minecraft/java/paper/egg-paper.json
```

Alternativ im Browser oeffnen und als JSON speichern.

### 2. Egg im Panel importieren

1. Panel oeffnen: `https://pelican.intern.rohrbom.be`
2. Admin-Bereich → **Eggs** (linke Leiste)
3. **Import Egg** (oben rechts)
4. JSON-Datei hochladen
5. Nest waehlen: `Minecraft` (neu anlegen falls nicht vorhanden)

Nach dem Import erscheint `Paper` in der Egg-Liste.

---

## Phase 2: Allokation anlegen

Im Panel: **Admin → Nodes → media-1 → Allocations**

Pruefen ob `172.26.50.31:25565` bereits vorhanden ist.
Falls nicht:

* IP Address: `172.26.50.31`
* Ports: `25565`

Wichtig: Immer die Game-IP `172.26.50.31` verwenden, nie die Management-IP `172.26.100.31`.

---

## Phase 3: Server anlegen

**Admin → Servers → Create New**

### Basis-Einstellungen

| Feld | Wert |
|---|---|
| Server Name | `minecraft-paper` |
| Owner | Admin-Account |
| Egg | `Paper` |
| Node | `media-1` |
| Primary Allocation | `172.26.50.31:25565` |
| Memory | `4096` MB (Minimum 2048, empfohlen 4096–8192) |
| Disk | `20480` MB |
| CPU | `400` % (4 vCPUs) |

### Egg-Variablen

| Variable | Wert | Erklaerung |
|---|---|---|
| Minecraft Version | `latest` | Aktuelle stabile Version |
| Build Number | `latest` | Neuester stabiler Paper-Build |
| Server Jarfile | `server.jar` | Standard, nicht aendern |

### Startup-Befehl mit Aikar's Flags

Im Startup-Feld des Servers die JVM-Flags auf Aikar's Flags setzen.
Das ist die Referenz-Konfiguration fuer Paper-Server:

```
java -Xms128M -XX:MaxRAMPercentage=95.0 -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1 -Dusing.aikars.flags=https://mcflags.emc.gs -Daikars.new.flags=true -jar {{SERVER_JARFILE}} --nogui
```

`-XX:MaxRAMPercentage=95.0` bedeutet: 95 % des dem Container zugewiesenen Speichers fuer die JVM-Heap.
Damit ist der Wert automatisch an den Pelican-Memory-Limit gebunden – kein manuelles `-Xmx` noetig.

---

## Phase 4: EULA und Erststart

Server im Panel starten. Beim ersten Start bricht Paper mit folgendem Hinweis ab:

```
You need to agree to the EULA in order to run the server.
Edit the eula.txt and change eula=false to eula=true
```

Im Pelican-File-Manager (Panel → Server → Files):

1. `eula.txt` oeffnen
2. `eula=false` → `eula=true`
3. Server neu starten

Server laeuft, wenn die Konsole zeigt:

```
Done (X.XXXs)! For help, type "help"
```

---

## Phase 5: Performance-Plugins installieren

Plugins werden in `/plugins/` abgelegt und werden nach einem Server-Neustart geladen.
Dateien per SFTP hochladen (`172.26.50.31:2022`) oder ueber den Pelican-File-Manager.

### Spark (unverzichtbar)

Spark ist ein In-Game-Profiler. Ohne ihn ist Performance-Diagnose blind.

Download: https://spark.lucko.me/download (Paper-Version)

Nutzung in der Server-Konsole:

```
spark tps
spark healthreport
spark profiler start
spark profiler stop
```

TPS-Zielwert: `20.0 / 20.0 / 20.0`. Unter 18 = Performance-Problem.

### Chunky (dringend empfohlen)

Chunky pregeneriert Chunks rund um den Spawn.
Verhindert Lag-Spikes, wenn Spieler neue Gebiete erkunden.

Download: https://modrinth.com/plugin/chunky

Nach dem ersten Start ausfuehren:

```
chunky world world
chunky radius 5000
chunky start
```

Laeuft im Hintergrund. Kann auch bei laufendem Spielbetrieb gestartet werden.

### ViaVersion (optional)

Erlaubt aelteren Minecraft-Clients, sich mit einem neueren Server zu verbinden.

Download: https://modrinth.com/plugin/viaversion

---

## Phase 6: paper.yml Performance-Tuning

Paper legt seine Konfiguration in `config/` ab (Paper 1.19+).

### `config/paper-world-defaults.yml`

```yaml
chunks:
  max-auto-save-chunks-per-tick: 24
  prevent-moving-into-unloaded-chunks: true

environment:
  optimize-explosions: true
  treasure-maps:
    enabled: false      # Treasure Maps koennen massive Lag-Spikes verursachen

entities:
  mob-spawner-tick-rate: 2

tick-rates:
  sensor:
    villager:
      secondarypoisensor: 80
  behavior:
    villager:
      validatenearbypoi: 60
```

### `config/paper-global.yml`

```yaml
console:
  enable-brigadier-completions: false   # Spart CPU fuer Konsolen-Autocomplete

packet-limiter:
  max-packet-rate: 500.0
```

### `server.properties` (wichtige Werte)

```properties
view-distance=10          # Default 10; bei wenig RAM/CPU auf 6-8 senken
simulation-distance=6     # Default 10; Mob-AI und Wasser nur in 6 Chunks
```

---

## Phase 7: Router-Portforward

Sobald der Server intern sauber laeuft:

* WAN → TCP+UDP Port `25565` → `172.26.50.31:25565`

Optional: Cloudflare-SRV-Eintrag fuer einen sauberen Hostnamen:

```
_minecraft._tcp.mc.deine-domain.de  SRV  0 5 25565 <WAN-IP oder DDNS-Host>
```

Wichtig: Cloudflare-SRV-Records koennen nicht ueber den Proxy laufen – Eintrag auf **DNS only** stellen.

---

## Schnelle Checks

### Server-Status in der Konsole

```
tps
memory
```

### Allokation pruefen (auf media-1)

```bash
ss -tlnp | grep 25565
```

Erwartung: Prozess lauscht auf `172.26.50.31:25565`.

### Wings-Log

```bash
sudo journalctl -u wings -n 100 --no-pager
```

---

## Erfolgskriterien

* Server startet sauber, Konsole zeigt `Done`
* TPS liegt bei `20.0 / 20.0 / 20.0` (Leerlauf)
* `spark tps` liefert eine Ausgabe
* Chunky-Pregenerierung laeuft
* Verbindung von einem Minecraft-Client intern moeglich
* Nach Portforward: Verbindung von aussen moeglich

---

## Referenzen

* Pelican Eggs Repository: https://github.com/pelican-eggs/eggs
* Paper-Egg direkt: https://github.com/pelican-eggs/eggs/tree/master/minecraft/java/paper
* Aikar's JVM Flags: https://mcflags.emc.gs
* Paper Konfigurationsdoku: https://docs.papermc.io/paper/reference/configuration
* Spark Profiler: https://spark.lucko.me
* Chunky: https://modrinth.com/plugin/chunky
* ViaVersion: https://modrinth.com/plugin/viaversion
* [`gameserver-pelican.md`](./gameserver-pelican.md)
