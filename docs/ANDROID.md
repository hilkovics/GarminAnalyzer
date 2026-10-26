# Aplikácia na Android mobile (bez zapnutého PC)

Celá aplikácia beží priamo v mobile. Každé ráno o 9:00 sa sama spustí synchronizácia s Garminom, prepočet,
návrh tréningu, odoslanie do Garmin kalendára a správa na Telegram. Aplikáciu otváraš ikonou na ploche.
PC na to netreba.

**Ako to funguje:** [Termux](https://termux.dev) je linuxové prostredie pre Android. V ňom beží malý Debian
(`proot-distro`), v ktorom ide tá istá Python aplikácia ako na PC, bez úprav. Overené na ARM procesore
(emulovanom): všetky knižnice sa nainštalujú ako hotové balíčky, 111 testov prešlo.

**Potrebuješ:** Android 8 alebo novší, asi 2 GB voľného miesta, Wi-Fi na prvú inštaláciu (stiahne ~400 MB).

## 1. Aplikácie z F-Droid

Nainštaluj [F-Droid](https://f-droid.org) a z neho štyri aplikácie: **Termux**, **Termux:API**, **Termux:Boot**
a **Termux:Widget**. Všetky musia byť z F-Droid. Verzia Termuxu v Google Play je zastaraná a s doplnkami
z F-Droid nefunguje.

## 2. Stiahnutie aplikácie do mobilu

Otvor Termux a zadaj (repozitár je súkromný, `gh` sa prihlási cez prehliadač):

```bash
pkg install -y git gh
gh auth login                      # GitHub.com → HTTPS → Login with a web browser
gh repo clone hilkovics/GarminAnalyzer ~/GarminAnalyzer
cd ~/GarminAnalyzer && git checkout claude/bold-cannon-0n04pi   # vetva, na ktorej teraz vyvíjame
# keď sa vetva neskôr zlúči do hlavnej: git checkout main && git pull
```

## 3. Prenos dát z PC

Na PC v priečinku aplikácie:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\export_for_phone.ps1
```

Skript zastaví aplikáciu na PC a do priečinka **`%USERPROFILE%\GarminAnalyzer-telefon`** (napr.
`C:\Users\hilko\GarminAnalyzer-telefon`) pripraví:
- `training.db` – databázu (konzistentná kópia);
- `garmin_tokens.json` – prihlásenie do Garminu;
- `env.txt` – nastavenia z `.env` (Telegram, AI report), ak ich na PC máš.

Zámerne nie na plochu, tú často zálohuje OneDrive do cloudu. Skript zároveň vypne rannú úlohu na PC, aby
tréningy do Garminu neposielali dve zariadenia naraz. Ak si chceš mobil najprv vyskúšať, pridaj `-KeepTask`
a úlohu vypni neskôr.

Súbory skopíruj do mobilu do priečinka **Download/GarminAnalyzer** USB káblom alebo cez Quick Share. Inštalácia
ich nájde aj priamo v Download alebo v Download/Quick Share. Nie cez Google Drive: je v nich tvoje prihlásenie
a kľúče. Po skopírovaní priečinok na PC zmaž.

Bez PC dát to ide tiež: vynechaj tento krok a po inštalácii spusti `garmin login` a
`garmin backfill --months 24` (sťahovanie histórie trvá niekoľko hodín).

## 4. Inštalácia v mobile

V Termuxe:

```bash
bash ~/GarminAnalyzer/scripts/android/setup.sh
```

Prvý raz to trvá 10–20 minút. Android sa raz opýta na prístup k súborom (kvôli priečinku Download), povoľ ho.
Ak skript napíše, že databázu nenašiel (povolenie prišlo neskoro alebo súbory sú inde), presuň ich v aplikácii
Súbory do Download/GarminAnalyzer a spusti ho znova. Ranný beh a aplikácia sa zapnú až vtedy, keď je databáza
v mobile.

Skript dá databázu, prihlásenie a nastavenia na miesto a prihlásenie a nastavenia z priečinka Download presunie
preč (sú to tajné údaje). Dá sa spustiť znova kedykoľvek: databázu, v ktorej už sú dáta, nikdy neprepíše.

**Telegram bez `env.txt`:** vytvor v Termuxe `nano ~/GarminAnalyzer/.env` s riadkami
`TRAINING_TELEGRAM_TOKEN=…` a `TRAINING_TELEGRAM_CHAT_ID=…` (rovnaké hodnoty ako na PC).

## 5. Nastavenia Androidu (dôležité pre beh o 9:00)

1. **Nastavenia → Aplikácie → Termux → Batéria → Bez obmedzení.** Inak Android môže ranný beh vynechať.
2. Raz otvor aplikáciu **Termux:Boot**. Po reštarte mobilu sa potom všetko spustí samo.
3. Na plochu pridaj **widget Termux**. Ukáže štyri tlačidlá:
   - **Ranny beh**: celý ranný beh hneď (sync, plán, Garmin, Telegram) s výpisom;
   - **Otvorit appku**: spustí aplikáciu a otvorí ju v Chrome;
   - **Aktualizovat**: stiahne novú verziu aplikácie, znova spustí inštaláciu (skripty, knižnice, ranný beh)
     a reštartuje ju;
   - **Zaloha**: kópia databázy do priečinka Download.
4. V Chrome otvor `http://127.0.0.1:8000`, potom **menu ⋮ → Pridať na plochu**. Aplikácia potom beží ako
   samostatná appka s ikonou.

## Každý deň

- Ráno sa hodinky zosynchronizujú s aplikáciou Garmin Connect ako doteraz.
- O 9:00 sa ranný beh spustí sám. Kým nie je spánok z hodiniek v Garmine, čaká a skúša každú hodinu do 13:00.
- Kedykoľvek to chceš hneď, ťukni na **Ranny beh** vo widgete.
- Výsledok vidíš v aplikácii (Dashboard, riadok „Ranný beh“) a v správe na Telegrame.

## Príkazy v Termuxe

```bash
garmin morning          # ranný beh teraz
garmin sync             # len synchronizácia
garmin plan-today       # dnešný tréning
garmin login            # nové prihlásenie do Garminu (keď prihlásenie vyprší)
garmin-server restart   # reštart aplikácie (http://127.0.0.1:8000)
garmin-backup           # záloha databázy do Download
crontab -l              # kontrola behu o 9:00
tail ~/GarminAnalyzer/data/logs/cron.out   # výpis posledných ranných behov
```

## Záloha

Databáza je v mobile v `~/GarminAnalyzer/data/training.db`. Občas ťukni na **Zaloha** vo widgete (alebo
`garmin-backup`). Do priečinka Download sa uloží `training-RRRR-MM-DD.db`. Kópia je konzistentná, aj keď
aplikácia práve beží.

Takto dostaneš databázu aj späť na PC, ak si tam chceš aplikáciu pozrieť: skopíruj ju do `data\training.db`.
Na PC však nezapínaj rannú úlohu, ranný beh má robiť len mobil.

## Keď niečo nejde

| Problém | Riešenie |
|---|---|
| O 9:00 nič neprebehlo | Skontroluj batériu (krok 5.1) a `crontab -l`. Po reštarte mobilu musí byť aspoň raz otvorený Termux:Boot. |
| Termux sa sám ukončuje (Android 12+) | Android obmedzuje procesy na pozadí. Android 14+: Nastavenia → Pre vývojárov → „Disable child process restrictions“. Staršie: cez `adb shell device_config put activity_manager max_phantom_processes 2147483647`. |
| Appka v Chrome sa nenačíta | Widget **Otvorit appku**, alebo `garmin-server restart`, a pozri `~/GarminAnalyzer/data/logs/server.out`. |
| Chyba prihlásenia do Garminu | `garmin login` (heslo zadávaš len ty, uloží sa len token). |
