# Domáci server – aplikácia beží nonstop

Cieľ: ranný beh o **9:00** (sync z Garminu → metriky → plán → odoslanie tréningu do Garminu → Telegram) prebehne
každý deň, aj keď je tvoj počítač vypnutý. Aplikáciu otvoríš z počítača aj z mobilu.

```
hodinky → Garmin Connect (mobil) → Garmin cloud
                                        ↓  9:00 každý deň
                     domáci server (Raspberry Pi / mini PC, Docker)
                       ├─ morning: sync, plán, push do Garminu
                       └─ app: React aplikácia + API (len na serveri: 127.0.0.1:8000)
                                        ↓  Tailscale (šifrované, HTTPS, len tvoje zariadenia)
                     počítač (ikona na ploche) · mobil (PWA ikona na ploche)
```

Server je doma, takže Garmin vidí tvoju domácu IP adresu (menšie riziko blokovania ako server v cloude) a zdravotné
dáta neopúšťajú domácnosť. Aplikácia nemá prihlásenie, preto nie je dostupná z internetu ani z domácej Wi-Fi –
iba cez Tailscale z tvojich prihlásených zariadení.

## 1. Hardvér (raz)

Odporúčané (cca 110–150 €):
- **Raspberry Pi 5, 4 GB** (alebo 8 GB) s **oficiálnym 27 W zdrojom**, krabička s ventilátorom;
- **USB SSD** 128 GB+ (odolnejší než microSD karta; SQLite zapisuje každý deň) – alebo aspoň kvalitná
  microSD karta A2, 64 GB;
- ethernetový kábel k routeru (spoľahlivejšie než Wi-Fi).

Funguje aj ľubovoľný starší notebook / mini PC s Linuxom (Debian/Ubuntu), ktorý necháš zapnutý.

**Mini PC (napr. Beelink SER9) – výborná voľba:** x86-64 je presne architektúra, na ktorej je Docker image otestovaný,
NVMe disk je spoľahlivejší než SD karta a výkonu je viac než dosť (aplikácia potrebuje < 1 GB RAM). Spotreba v
nečinnosti býva okolo 6–10 W (cca 15–25 € ročne). Odporúčaný postup – mini PC venovať len serveru:
- nainštaluj **Ubuntu Server 24.04 LTS** (USB kľúč z ubuntu.com, pri inštalácii zaškrtni *Install OpenSSH server*,
  hostname `trening`) – Windows z neho zmizne;
- v BIOSe (pri štarte F7/Del) nastav **„Power on after AC loss“ / „Restore on AC power loss“ = Power On**, aby sa po
  výpadku prúdu zapol sám;
- potom pokračuj krokom 3 (prihlásenie `ssh samuel@trening.local`, Docker, Tailscale) – je rovnaký ako pri Pi.

Ak chceš na mini PC nechať Windows (napr. ho používaš aj na iné veci), dá sa to – ranný beh cez Plánovač úloh
(`install_task_windows.ps1`) a aplikácia cez `start_app.ps1` + Tailscale pre Windows. Musí však ostať zapnutý,
prihlásený a s vypnutým uspávaním, a reštarty po aktualizáciách Windows ho občas vyradia; Linux s Dockerom je
na nonstop beh spoľahlivejší.

## 2. Inštalácia systému (raz, cca 20 min) – Raspberry Pi

(Mini PC s Ubuntu: pozri vyššie a pokračuj krokom 3.)

1. Na počítači stiahni **Raspberry Pi Imager** (raspberrypi.com/software).
2. Vyber *Raspberry Pi 5* → *Raspberry Pi OS Lite (64-bit)* → tvoj SSD/kartu.
3. V nastaveniach (ozubené koliesko / „Edit settings“):
   - hostname: `trening`;
   - používateľ: napr. `samuel` + heslo;
   - Wi-Fi (ak nepoužiješ kábel), časové pásmo `Europe/Bratislava`;
   - záložka *Services*: **Enable SSH** (s heslom).
4. Zapíš, vlož do Pi, zapoj a počkaj 2 minúty.
5. Na počítači v PowerShelli: `ssh samuel@trening.local` (prvýkrát potvrď `yes`).

## 3. Príprava servera (raz, cez SSH)

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt install -y git
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # vypíše odkaz – otvor ho a prihlás sa (Google/Microsoft/GitHub účet)
exit                          # odhlás sa a znova sa prihlás (ssh samuel@trening.local), aby platila skupina docker
```

Projekt (súkromné repo → GitHub si vypýta meno a **token**: GitHub → Settings → Developer settings →
Fine-grained tokens → prístup *Contents: Read* len k tomuto repu):
```bash
git clone -b claude/bold-cannon-0n04pi https://github.com/hilkovics/garminanalyzer.git GarminAnalyzer
git config --global credential.helper store   # aby sa token pri ďalšom `git pull` nepýtal
```

**Tailscale aj na počítači a mobile:** nainštaluj aplikáciu Tailscale (tailscale.com/download, v mobile z obchodu)
a prihlás sa rovnakým účtom. V administrácii Tailscale (login.tailscale.com → DNS) zapni **MagicDNS** a
**HTTPS Certificates** (prvé `tailscale serve` ťa na to aj upozorní).

## 4. Presun dát z počítača (raz, na Windows)

V priečinku projektu na počítači:
```powershell
git pull
powershell -ExecutionPolicy Bypass -File scripts\move_to_server.ps1 -Server samuel@trening.local
```
Skript zastaví aplikáciu na počítači, skopíruje databázu (`data\training.db`) a Garmin prihlásenie (tokeny) na
server a **odstráni rannú úlohu z Windows** – odteraz synchronizuje a posiela tréningy do Garminu iba server
(dva počítače s dvoma databázami by posielali každý tréning dvakrát). Heslo k serveru zadáš ty, nikde sa neukladá.
Lokálna kópia dát na počítači ostáva ako záloha.

## 5. Spustenie servera (raz, cez SSH)

```bash
cd GarminAnalyzer
scripts/server_setup.sh
```
Skript vytvorí `.env` (čas 9:00, časové pásmo, tvoj používateľ), zostaví a spustí kontajnery (prvé zostavenie na Pi
trvá niekoľko minút), overí, že aplikácia odpovedá, a sprístupní ju cez Tailscale. Na konci vypíše adresu, napr.
`https://trening.tail1234.ts.net/`.

Voliteľné (Telegram, AI report): dopíš do `.env` na serveri `TRAINING_TELEGRAM_TOKEN=…`, `TRAINING_TELEGRAM_CHAT_ID=…`,
`TRAINING_ANTHROPIC_API_KEY=…` a spusti `docker compose up -d`.

## 6. Ikona na počítači a v mobile

- **Počítač:** `powershell -ExecutionPolicy Bypass -File scripts\install_shortcut_windows.ps1 -Url https://trening.tail1234.ts.net`
  – ikona *Training Analytics* otvorí aplikáciu zo servera ako samostatné okno (na počítači už nič nebeží).
- **Mobil:** otvor adresu v prehliadači (Tailscale musí byť zapnutý) → *Pridať na plochu* / *Inštalovať aplikáciu*.

## Prevádzka

| Čo | Príkaz (na serveri v `~/GarminAnalyzer`) |
| --- | --- |
| Stav kontajnerov | `docker compose ps` |
| Priebeh ranného behu | `docker compose logs -f morning` (a v aplikácii Nastavenia → Sync a diagnostika) |
| Spustiť ranný beh hneď | `docker compose exec morning training morning` |
| Sync teraz | tlačidlo v Nastaveniach, alebo `docker compose exec morning training sync` |
| Aktualizácia aplikácie | `git pull && docker compose up -d --build` |
| Zmena času ranného behu | v `.env` `MORNING_AT=08:30`, potom `docker compose up -d` |
| Reštart / vypnutie | `docker compose restart` / `docker compose down` |
| Nové Garmin prihlásenie | na počítači `uv run training login`, potom `scp $env:USERPROFILE\.garminconnect\garmin_tokens.json samuel@trening.local:.garminconnect/` (PowerShell) a na serveri `docker compose restart` |

- **Výpadok prúdu / reštart:** kontajnery sa spustia samy (`restart: unless-stopped`). Ak server o 9:00 nebežal,
  ranný beh dobehne hneď po štarte.
- **Keď ranný beh zlyhá** (napr. výpadok internetu alebo Garminu), server ho v ten deň skúsi znova každú hodinu,
  najviac 4-krát (10:00 … 13:00). Opakovanie je bezpečné – nič sa nezduplikuje.
- **Zálohy:** raz za čas skopíruj databázu na počítač:
  `scp samuel@trening.local:GarminAnalyzer/data/training.db zaloha-training.db` (v PowerShelli). Všetky surové
  dáta z Garminu sa dajú aj znova stiahnuť (`training backfill`), prahy a nastavenia by si však zadával znova.
- **Logy:** `data/logs/training.log` na serveri (JSON, tokeny maskované).
- Postup pri problémoch s prihlásením do Garminu: `docs/OPERATIONS.md` §3 (príkazy spúšťaj cez
  `docker compose exec morning …`).
