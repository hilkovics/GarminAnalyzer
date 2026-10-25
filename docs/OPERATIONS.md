# Prevádzka – Training Analytics

Ako aplikácia beží každý deň sama, kde sú logy a čo robiť, keď niečo zlyhá. Všetky príkazy spúšťaj v priečinku projektu.

## 0. Aplikácia na počítači

Aplikácia beží u teba: lokálny server (`uv run training api`) servíruje webovú aplikáciu aj API na
`http://127.0.0.1:8000`. Dáta neopúšťajú počítač a server nie je dostupný z iných zariadení (API nemá prihlásenie).

**Ikona na ploche (Windows), raz:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1            # ikona na plochu a do Štartu
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Remove    # odstrániť
```
Dvojklik na **Training Analytics**:
- spustí server, ak ešte nebeží (minimalizované okno „Training Analytics server“; jeho zatvorenie server vypne);
- otvorí aplikáciu ako samostatné okno v Microsoft Edge (inak v predvolenom prehliadači).

Ručne: `powershell -ExecutionPolicy Bypass -File scripts\start_app.ps1` (spustiť a otvoriť), s `-Stop` server vypne.
Výstup servera: `data\logs\app.out`. Prvé spustenie môže trvať dlhšie (uv inštaluje balíčky, databáza sa aktualizuje).

**Bez ikony:** `uv run training api` a v prehliadači `http://127.0.0.1:8000`.
Stará Streamlit verzia zostáva do odvolania: `uv run streamlit run ui-streamlit/app.py` (port 8501).

**Mobil:** aplikácia je pripravená ako PWA (ikona na plochu telefónu), ale telefón sa k serveru na počítači
nedostane – server počúva len na tomto počítači a inštalácia PWA vyžaduje HTTPS. Bezpečná cesta je napríklad
Tailscale (`tailscale serve`), nastavíme ju, keď budeš chcieť.

**Úpravy frontendu (len pre vývoj):** `cd frontend && npm ci && npm run dev` (port 5173, API cez proxy) a pred
commitom `npm run build` – priečinok `frontend/dist` je v gite, aby aplikácia bežala aj bez Node.js.

## 1. Denný beh: `training morning`

Jeden príkaz urobí celé ráno v tomto poradí:

| Krok | Čo robí | Keď zlyhá |
| --- | --- | --- |
| sync | Stiahne nové aktivity a wellness z Garmin Connect a prepočíta metriky. | Beh pokračuje. Plán zostane predbežný a do Garminu sa nepošle. |
| plan | Naplánuje dnešný tréning (alebo prepočíta predbežný plán). | Push sa preskočí. |
| push | Pošle tréning do Garmin Connect kalendára. Nezmenený plán sa nepošle znova. | Zapíše sa chyba, ostatné kroky bežia ďalej. |
| telegram | Pošle rannú správu, najviac raz za deň (ak je nastavený). | Zapíše sa chyba a pri ďalšom behu sa skúsi znova. |

```powershell
uv run training morning                  # celý beh
uv run training morning --no-push        # bez odoslania do Garminu
uv run training morning --no-telegram
uv run training morning --force-telegram # pošli správu aj druhýkrát v ten istý deň
```

- **Opakovanie:** dá sa spustiť koľkokrát chceš. Nič sa nezduplikuje: sync, plán ani tréning v Garmine.
- **Návratový kód:**
  - `0` = všetko v poriadku;
  - `1` = niektorý krok zlyhal;
  - `3` = práve beží iný ranný beh (zámok `data/logs/morning.lock`; zámok starší ako 3 hodiny sa prevezme).
- **Logy:**
  - `data/logs/training.log` – JSON riadky, rotácia po 5 MB, 10 súborov. Tokeny a kľúče sa v nich maskujú.
  - `data/logs/task.out` (Windows) a `data/logs/cron.out` (Linux/macOS) – výstup plánovača.
- **Kde vidieť výsledok:**
  - Dashboard – riadok „Ranný beh“, červený pri chybe alebo keď 36 hodín nebežal úspešne.
  - Nastavenia → Sync a diagnostika – posledných 10 behov a posledné chyby.
- **Časy** v aplikácii a v logu sú v lokálnom časovom pásme počítača (v Dockeri podľa `TZ`); log má pri čase aj posun voči UTC. V databáze sú časy behov uložené v UTC.

## 2. Automatické spúšťanie

Pred prvým spustením sa raz prihlás: `uv run training login`, potom `uv run training whoami`.

### Windows (Plánovač úloh)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1            # denne o 06:00
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -At 05:45  # iný čas
Start-ScheduledTask -TaskName "GarminAnalyzer - training morning"                    # vyskúšaj hneď
Get-ScheduledTaskInfo -TaskName "GarminAnalyzer - training morning"                  # LastTaskResult 0 = OK
powershell -ExecutionPolicy Bypass -File scripts\install_task_windows.ps1 -Remove    # odstrániť
```

Úloha beží pod tvojím účtom, keď si prihlásený. Ak bol počítač o 06:00 uspatý, spustí sa po zobudení, hneď ako je pripojený na internet. Výsledok uvidíš aj v aplikácii *Plánovač úloh* pod rovnakým názvom.

### Linux / macOS (cron)

```bash
scripts/install_cron.sh          # denne o 06:00
scripts/install_cron.sh 05:45
scripts/install_cron.sh --remove
crontab -l                       # kontrola
```

### Docker (Raspberry Pi, NAS, domáci server)

`docker-compose.yml` má dve služby z jedného image:
- `ui` – Streamlit na porte 8501;
- `morning` – `training morning --loop`, beží denne o `MORNING_AT` (predvolene 06:00) v časovom pásme `TZ` (predvolene Europe/Bratislava).

1. **Tokeny (raz, na hostiteľovi):** prihlás sa mimo kontajnera – heslo a MFA sa do kontajnera nedajú zadať:
   ```bash
   uv run training login        # tokeny → ~/.garminconnect/garmin_tokens.json
   ```
   Priečinok s tokenmi sa pripája do kontajnera ako `/tokens`. Iné umiestnenie nastavíš cez `GARMIN_TOKENS_DIR=/cesta`.
   Ak na serveri nie je `uv`, prihlás sa na inom počítači a súbor `garmin_tokens.json` prenes do `~/.garminconnect/` na serveri.
2. **Voliteľné tajomstvá** – súbor `.env` vedľa `docker-compose.yml` (nie je v gite):
   ```
   TRAINING_TELEGRAM_TOKEN=...
   TRAINING_TELEGRAM_CHAT_ID=...
   TRAINING_ANTHROPIC_API_KEY=...
   ```
3. **Spustenie:**
   ```bash
   docker compose up -d --build
   docker compose logs -f morning      # priebeh ranného behu
   docker compose exec morning uv run --no-sync training morning   # spusti hneď
   ```

- Kontajnery bežia pod tvojím používateľom (`UID`/`GID`, predvolene 1000), aby súbor s tokenmi a `./data` zostali tvoje. Ak máš iné UID, zapíš `UID=…` a `GID=…` do `.env` (zistíš ich príkazom `id`).
- Databáza, logy aj týždenné AI reporty (`data/reports`) sú v `./data` na hostiteľovi, takže prebudovanie image nič nezmaže. `./data` má byť na lokálnom disku, nie na sieťovom zdieľaní (SQLite).
- Ranný beh v Dockeri čaká na `MORNING_AT` podľa nástenných hodín, takže zmenu času zvládne. Ak kontajner v daný deň po `MORNING_AT` ešte nebežal (reštart, výpadok), beh dobehne hneď po štarte.
- `docker-compose.yml` vyžaduje Docker Compose 2.24 alebo novší. Image zatiaľ nebol vyskúšaný na Raspberry Pi.

## 3. Keď prestane fungovať prihlásenie do Garminu

Garmin z času na čas zmení prihlasovanie a knižnica `garminconnect` potrebuje aktualizáciu. **Nič sa nestratí:** databáza je len kópia dát z Garminu a všetky stiahnuté odpovede sú uložené. Keď sa prihlásenie opraví, ďalší `sync` dobehne zameškané dni.

**Príznaky:**
- ranný beh má krok `sync` = ✗ a správu „Garmin login is missing or was rejected…“;
- `uv run training whoami` zlyhá;
- prípadne chyba 429 alebo 403.

**Postup:**
1. **429 alebo 403 (Cloudflare, príliš veľa požiadaviek):** neskúšaj to dookola, každý pokus blokovanie predlžuje. Počkaj niekoľko hodín a skús to raz, ideálne z inej siete (napríklad hotspot z mobilu).
2. **Over tokeny:** `uv run training whoami`. Ak fungujú, problém je len prechodný a ďalší beh to dobehne.
3. **Prihlás sa znova:** `uv run training login --force`. Pôvodné tokeny sa počas prihlasovania odložia a ak prihlásenie zlyhá, vrátia sa späť.
4. **Aktualizuj knižnicu:**
   ```bash
   uv lock --upgrade-package garminconnect
   uv sync --extra ai
   uv run pytest -q
   ```
   Ak testy prejdú, commitni `uv.lock` a znova sa prihlás.
5. **Ak nepomôže ani nová verzia,** čakaj na opravu v knižnici (GitHub `cyberjunky/python-garminconnect`, sekcia issues). Aplikácia medzitým funguje nad už stiahnutými dátami, len bez nových.
6. **Po oprave:** `uv run training sync` (alebo `sync --retry-failed`, ak sú niektoré dni označené ako zlyhané). Chýbajúce dni sa dotiahnu samy.

## 4. Obnova a zálohy

- **Záloha:** stačí `data/training.db`, napríklad raz týždenne skopírovať. Tokeny (`~/.garminconnect`) sa dajú vždy vytvoriť znova prihlásením.
- **Prepočet bez internetu:** `uv run training recompute` – všetky metriky z uložených odpovedí Garminu, napríklad po zmene prahov alebo po aktualizácii aplikácie.
- **Úplne od nuly:** premenuj `data/training.db` a spusti `uv run training backfill --months 24`. Prahy a údaje atléta potom zadaj znova.
- **Prerušený backfill:** rovnaký príkaz pokračuje tam, kde skončil. `--restart` prejde celé obdobie znova.

## 5. Časté situácie

| Situácia | Čo urobiť |
| --- | --- |
| Dashboard: „Posledný sync je starší ako 36 hodín“ | Pozri Nastavenia → Sync a diagnostika a `data/logs/training.log`. Skontroluj, či plánovač beží (`Get-ScheduledTaskInfo` alebo `crontab -l`). |
| Dashboard: „Posledný ranný beh zlyhal“ | V Nastavenia → Sync a diagnostika uvidíš, ktorý krok zlyhal. Ak len Telegram alebo push, dáta sú v poriadku. Spusti `uv run training morning` znova. |
| Dashboard: „Posledný úspešný ranný beh je starší ako 36 hodín“ | Plánovač nebeží alebo každý beh padá – skontroluj úlohu (`Get-ScheduledTaskInfo`, `crontab -l`, `docker compose ps`) a log. |
| Ranný beh vracia kód 3 | Iný beh ešte beží. Zámok `data/logs/morning.lock` po spadnutom behu sa sám prevezme (Linux okamžite, inak po 3 hodinách); v Dockeri je ten istý súbor v `./data/logs`. |
| Tréning sa neobjavil na hodinkách | V Garmin Connect skontroluj kalendár, potom synchronizuj hodinky. Na stránke Plán musí byť stav „odoslané“. |
| Telegram neprišiel | Spusti `uv run training telegram-morning --dry-run` (len vypíše správu), skontroluj premenné prostredia a pozri log. |
| Testy padajú na `anthropic` | Spusti `uv sync --extra ai`, prípadne ignoruj – testy AI reportu sa bez tohto doplnku preskočia. |
