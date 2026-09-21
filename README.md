# FEA COACH APP v1.1

Docelowa wersja pierwszego pełnego workflow FEA COACH SYSTEM.

## Główny obieg
Mecz → diagnoza → priorytet → poniedziałek → Training Score → karta analizy → środa → Training Score → karta analizy → piątek → Training Score → kolejny mecz → weryfikacja transferu i pamięć problemu.

## v1.1
- Dashboard „Co teraz wymaga decyzji trenera?”
- status całego mikrocyklu i postęp workflow
- podsumowanie trendu R/W/P/G
- rozdzielenie wyniku treningowego od weryfikacji meczowej
- automatyczne archiwizowanie poprzedniego mikrocyklu przy rozpoczęciu nowej analizy meczu
- pamięć problemów między mikrocyklami
- dynamiczna adaptacja PON → ŚR → PT
- karta analizy przed zatwierdzeniem kolejnej jednostki
- biblioteki FEA i Motoryki, ręczne podmiany, skuteczność środków
- konspekt PDF generowany z aktualnego planu

## Uruchomienie
```bash
pip install -r requirements.txt
streamlit run app.py
```

Dane robocze są zapisywane lokalnie w `data/state.json`.


## v1.1 — profil środka i lepszy dobór
- każdy środek FEA otrzymuje automatyczny profil PER/DEC/EXE, presji, transferu i złożoności,
- dobór uwzględnia etap R/W/P/G i decyzję PROGRESS/CONTINUE/REGRESS/CHANGE,
- dopasowanie tekstowe jest tylko jednym z elementów, nie głównym kryterium,
- konspekt pokazuje „Dlaczego ten środek”,
- Biblioteka FEA pokazuje profil Presja 1–5 i Transfer 1–5.
