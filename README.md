# FEA COACH APP v0.5 – silnik diagnozy trenerskiej

Nowości v0.5:
- analiza problemu w osiach PER / DEC / EXE / PRESSURE / TRANSFER / MENTAL,
- profil R/W/P/G nie jest traktowany wyłącznie jako średnia,
- silnik opisuje prawdopodobną przyczynę problemu i zalecany kierunek kolejnej jednostki,
- dobór środków uwzględnia jednocześnie opis problemu, obserwację trenera, obszar analizy i najsłabszy element R/W/P/G,
- PROGRESS / CONTINUE / REGRESS / CHANGE wpływa na ponowny dobór kolejnej jednostki,
- przy co najmniej 2 ocenionych użyciach historia skuteczności może wspierać kolejność kandydatów, ale nie zastępuje dopasowania do problemu,
- „Analizuj ponownie” korzysta z aktualnej Biblioteki FEA/Motoryki.

## Uruchomienie
1. Zainstaluj Python 3.11+.
2. W katalogu aplikacji: `pip install -r requirements.txt`
3. Uruchom: `streamlit run app.py`
4. Otwórz adres pokazany przez Streamlit.

To nadal prototyp lokalny. Dane są zapisywane w `data/state.json` i plikach bibliotek JSON.
