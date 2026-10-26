# Tréner „Kondícia“

Stav: **schválené 2026-10-26.** Záväzné pravidlá sú v `docs/METRICS.md` §11 (tento dokument je zdôvodnenie).
Krok 1 implementovaný 2026-10-26; kroky 2 a 3 nasledujú. Čísla sú počiatočné – dajú sa zmeniť (najprv v METRICS).

## Rozhodnutia používateľa (2026-10-26)

- Cieľ: lepšia kondícia čo najefektívnejšie popri zlom spánku; preteky zatiaľ nie (možno neskôr).
- Pokrok merať: **rýchlejší čas na 5/10 km** a **rýchlejšie tempo pri rovnakom tepe**.
- **3 behy týždenne**, cez pracovný týždeň **do 60 min**; primárne beh.
- Po zlej noci **automaticky prehodiť** tréning (do Garminu ide už upravený).
- Víkendová jazda na bicykli: **navyše, neplánovaná** – ráta sa do únavy a ovplyvní ďalší deň.
- **Kontrolný beh každých 6 týždňov** (5 km alebo 30 min naplno bez zastavenia).
- Ak o 9:00 v Garmine ešte nie je dnešný spánok: **počkať do 12:00** (skúšať každú hodinu), potom rozhodnúť bez neho.

## 1. Kedy platí

- **Bez cieľových pretekov → režim Kondícia** (tento návrh).
- **S cieľovými pretekmi → doterajší režim** (fázy Základ / Budovanie / Vrchol / Ladenie, METRICS §10) – nič sa nezahadzuje.

## 2. Týždenné menu namiesto pevných dní

Každý týždeň (Po–Ne) má 3 behy, ktoré si aplikácia rozloží podľa toho, ako sa ti darí:

| Beh | Čo | Kedy |
| --- | --- | --- |
| **K – kvalitný** | intervaly / tempo (pre 5 a 10 km) | len v „zelený“ deň |
| **D – dlhší** | pokojný beh v zóne 2 | najradšej cez víkend, nie v „červený“ deň |
| **Ľ – ľahký** | pokojný beh v zóne 2 | hocikedy okrem „červeného“ dňa |

- Dni, keď nemôžeš (na stránke Plán: preferované dni = „Voľno“), sa nepoužijú. Predvolene sú dostupné všetky dni.
- Každý 6. týždeň (6. a 12. týždeň bloku) nahradí K **kontrolný beh**.
- Nesplnené behy v nedeľu prepadnú – nič sa nedoháňa v ďalšom týždni.

## 3. Denné rozhodnutie (každé ráno po synchronizácii)

**Farba dňa** z pripravenosti P (METRICS §8, 0–100): **zelená** P ≥ 70 · **žltá** 45 ≤ P < 70 · **červená** P < 45.
Ak P chýba (žiadne wellness dáta ani o 12:00), deň sa berie ako žltý.

**„Včera tvrdo“** = včera bol K, D alebo kontrolný beh, alebo akákoľvek aktivita s IF ≥ 0,85, alebo jazda ≥ 90 min
(dochádzka sa nepočíta).

Pravidlá v tomto poradí (prvé, ktoré sedí, rozhodne):

1. **Červený deň → voľno** (spánok má prednosť pred tréningom).
2. **Včera tvrdo → Ľ** (ak ešte zostáva), inak voľno. Nikdy dva tvrdé dni po sebe.
3. **Zelený deň a K zostáva → K** (alebo kontrolný beh v testovom týždni).
4. **D zostáva a (je sobota/nedeľa alebo „musím“) → D.**
5. **Ľ zostáva → Ľ** – ale len ak „musím“ alebo je to aspoň druhý deň bez behu; inak voľno (behy sa rozložia).
6. **K zostáva, „musím“ a žltý deň → miernejší kvalitný** (tempo v zóne 3 namiesto intervalov).
7. Inak **voľno**.

**„Musím“** = počet zostávajúcich dostupných dní do nedele (vrátane dneška) ≤ počet nesplnených behov.

Rozhodnutie a dôvod sa uložia a o 9:00 (alebo po príchode spánku, najneskôr 12:00) sa tréning pošle do Garminu.
Keď v ten deň už je odbehnutý tréning, ráta sa ako splnený (párovanie ako dnes, dochádzka sa nepočíta).

## 4. Dĺžka a obsah tréningov

**Týždenný čas behu T:** na štart medián týždenného času behu z posledných 4 týždňov, najmenej 90 min.
Rozdelenie: **D 40 % · K 30 % · Ľ 30 %** (vrátane rozcvičenia a vyklusania), v rámci limitov:
**Ľ 25–60 min · K 35–60 min · D 45–100 min** (D len v sobotu/nedeľu môže presiahnuť 60 min).

**Progresia (bloky po 4 týždňoch):** 3 týždne **+7 %**, 4. týždeň **−30 %** (regenerácia).
Brzda podľa spánku a únavy (za posledných 7 dní):
- priemerná pripravenosť < 55 **alebo** spánkový dlh (METRICS §9) > 5 h → T sa **nezvyšuje**;
- priemerná pripravenosť < 45 → T **−15 %**;
- ACWR > 1,3 → T sa nezvyšuje.

**Kvalitné tréningy (rotujú, cieľ 5 a 10 km):** rozcvička 10–15 min Z2, vyklusanie 10 min Z1, jadro:
1. prahové intervaly 3–5 × 6 min Z4 / 2 min Z1;
2. VO2max 5–6 × 3 min Z5 / 3 min Z1;
3. tempo 15–25 min Z3–Z4;
4. kopce 6–10 × 60 s Z5, späť dolu pomaly.
Počet opakovaní / minúty sa zvolia podľa času pre K (ako dnes podľa odhadu záťaže).

**Miernejší kvalitný:** tempo 15–20 min Z3. **Kontrolný beh:** rozcvička 15 min Z2, **5 km naplno bez zastavenia**
(vypnutá auto-pauza), vyklusanie 10 min.

## 5. Bicykel

Neplánuje sa. Jazda sa ráta do únavy a formy (ako dnes); dlhá alebo intenzívna jazda je „včera tvrdo“ (pravidlo 2).
Dochádzka ostáva len únava.

## 6. Blok 12 týždňov a pokrok

- Na začiatku bloku sa uloží **východisko**: tempo pri referenčnom tepe (80 % LTHR, METRICS §6.1), odhad času
  na **5 km a 10 km** (METRICS §7), efektivita (EF).
- Každý týždeň: aktuálne hodnoty, zmena oproti východisku a trend.
- Kontrolné behy (6. a 12. týždeň) dajú presný čas na 5 km, spresnia odhad 10 km a dajú dáta pre návrhy prahov
  (30 min tepu bez pauzy).
- Na konci bloku súhrn (čo sa zlepšilo, koľko tréningov sa podarilo, vplyv spánku) a nový blok s T z posledných týždňov.

## 7. Predpovede

1. **Ranná poznámka:** z tvojej histórie behov a spánku (min. 30 dní s oboma) vzťah medzi spánkom minulej noci
   a tempom pri referenčnom tepe (očistený od únavy – TSB), napr. *„po 5,5 h spánku je tvoje ľahké tempo zvyčajne
   o ~12 s/km pomalšie – drž sa tepu, nie tempa“*. Ukáže sa, len keď je vzťah spoľahlivý (interval neistoty
   neobsahuje 0); inak „zatiaľ málo dát“.
2. **Výhľad na 7 dní:** pre každý deň odhad pripravenosti – forma z naplánovanej záťaže + tvoj typický spánok,
   pokojový tep a Body Battery pre daný deň v týždni (medián posledných 8 týždňov), dosadené do vzorca
   pripravenosti (METRICS §8). Označí **najlepšie dni na kvalitný tréning**. Je to orientačné; skutočné rozhodnutie
   padá každé ráno podľa skutočnej noci.

## 8. Postup implementácie

1. ✓ (2026-10-26) Pravidlá do METRICS §11 → denné rozhodnutie, týždenný čas, čakanie na spánok do 12:00, odoslanie do Garminu,
   stránka Plán (menu týždňa K/D/Ľ, farba dňa, dôvod).
2. Blok a pokrok (východisko, kontrolné behy, súhrn) – Plán a Progres.
3. Predpovede (ranná poznámka, 7-dňový výhľad) – Dashboard a Plán.

## Otvorené body (navrhujem takto, ak nepovieš inak)

- Prahy farieb 70 / 45 sú prevzaté z pripravenosti; pri dlhodobo zlom spánku môže byť zelených dní málo – po
  4 týždňoch vyhodnotíme, koľko K sa reálne podarilo, a prípadne prahy posunieme (napr. K aj pri P ≥ 60).
- Zóny tepu v Garmin Connect musia sedieť s LTHR 172 (tréningy sa posielajú ako „zóna 2, 4…“).
