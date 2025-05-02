import os
import pyaudio
import wave
import speech_recognition as sr
import googlemaps
import re
import audioop
from collections import deque

# Konfiguracja
GOOGLE_API_KEY = ''  #your api from google cloud
NAZWA_MIKROFONU = ""  #micro
CZAS_CISZY_PRZERWANIE = 1.5  
PROG_GLOSNOSCI = 500  
MAKS_CZAS_NAGRYWANIA = 15  #max record

# Inicjalizacja klienta Google Maps
gmaps = googlemaps.Client(key=GOOGLE_API_KEY)

def znajdz_id_mikrofonu(nazwa_fragment):
    """Znajduje ID mikrofonu na podstawie fragmentu nazwy"""
    p = pyaudio.PyAudio()
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if nazwa_fragment.lower() in info['name'].lower():
            print(f"✅ Wybrano mikrofon: {info['name']} (ID: {i})")
            return i
    print("❌ Nie znaleziono mikrofonu.")
    return None

def nagraj_audio():
    """Nagrywa audio aż do wykrycia ciszy, komendy 'koniec' lub osiągnięcia maksymalnego czasu"""
    FORMAT = pyaudio.paInt16
    KANALY = 1
    CZESTOTLIWOSC = 16000
    ROZMIAR_RAMKI = 1024

    audio = pyaudio.PyAudio()
    mikrofon_id = znajdz_id_mikrofonu(NAZWA_MIKROFONU)
    
    if mikrofon_id is None:
        print("❌ Brak mikrofonu! Przerywam.")
        return None

    # Przygotuj ścieżkę do pliku na Pulpicie
    pulpit = os.path.join(os.path.expanduser('~'), 'Desktop')
    numer = 1
    while True:
        sciezka_pliku = os.path.join(pulpit, f"nagranie_{numer}.wav")
        if not os.path.exists(sciezka_pliku):
            break
        numer += 1

    print(f"\n🎙️ Nagrywanie... Mów wyraźnie. Powiedz 'koniec' lub zamilknij na {CZAS_CISZY_PRZERWANIE}s aby zakończyć.")
    
    stream = audio.open(format=FORMAT, channels=KANALY,
                      rate=CZESTOTLIWOSC, input=True,
                      input_device_index=mikrofon_id,
                      frames_per_buffer=ROZMIAR_RAMKI)

    ramki = []
    cisza_licznik = 0
    nagrywanie_aktywne = True
    historia_rms = deque(maxlen=10)  

    while nagrywanie_aktywne:
        dane = stream.read(ROZMIAR_RAMKI, exception_on_overflow=False)
        ramki.append(dane)
        
        # Analiza poziomu dźwięku
        rms = audioop.rms(dane, 2)
        historia_rms.append(rms)
        sredni_rms = sum(historia_rms) / len(historia_rms) if historia_rms else 0
        
        # Sprawdź czy jest cisza
        if sredni_rms < PROG_GLOSNOSCI:
            cisza_licznik += ROZMIAR_RAMKI / CZESTOTLIWOSC
            if cisza_licznik > CZAS_CISZY_PRZERWANIE:
                print("🛑 Wykryto ciszę - kończenie nagrywania.")
                nagrywanie_aktywne = False
        else:
            cisza_licznik = 0
            
            # Sprawdź czy nie przekroczono maksymalnego czasu
            if len(ramki) * ROZMIAR_RAMKI / CZESTOTLIWOSC > MAKS_CZAS_NAGRYWANIA:
                print(f"🛑 Osiągnięto maksymalny czas nagrywania ({MAKS_CZAS_NAGRYWANIA}s).")
                nagrywanie_aktywne = False

    # Zakończ nagrywanie
    stream.stop_stream()
    stream.close()
    audio.terminate()

    # Zapisz plik WAV
    with wave.open(sciezka_pliku, 'wb') as plik_wave:
        plik_wave.setnchannels(KANALY)
        plik_wave.setsampwidth(audio.get_sample_size(FORMAT))
        plik_wave.setframerate(CZESTOTLIWOSC)
        plik_wave.writeframes(b''.join(ramki))

    print(f"✅ Zapisano nagranie ({len(ramki)*ROZMIAR_RAMKI/CZESTOTLIWOSC:.1f}s): {sciezka_pliku}")
    return sciezka_pliku

def rozpoznaj_mowe(sciezka_pliku):
    """Rozpoznaje mowę z pliku audio używając Google Speech Recognition"""
    r = sr.Recognizer()

    with sr.AudioFile(sciezka_pliku) as zrodlo:
        print("🧠 Rozpoznawanie mowy...")
        audio_data = r.record(zrodlo)

        try:
            tekst = r.recognize_google(audio_data, language='pl-PL')
            print(f"✅ Rozpoznano: {tekst}")
            return tekst
        except sr.UnknownValueError:
            print("❌ Nie zrozumiano, powiedz wyraźniej.")
        except sr.RequestError as e:
            print(f"❌ Błąd połączenia z serwerem: {e}")

def popraw_adres(adres):
    """Poprawia typowe błędy w rozpoznawaniu mowy dla adresów"""
    poprawki = {
        r'\bulicy\b': 'ulica',
        r'\baleji\b': 'aleja',
        r'\balei\b': 'aleja',
        r'\balek\b': 'aleja',
        r'\bul\b': 'ulica',
        r'\bpl\b': 'plac',
        r'\bplacu\b': 'plac',
        r'\bkoniec\b': '',  # Usuń słowo 'koniec' jeśli zostało rozpoznane
    }
    
    for wzorzec, zamiennik in poprawki.items():
        adres = re.sub(wzorzec, zamiennik, adres, flags=re.IGNORECASE)
    
    return adres.strip()

def przetworz_tekst(tekst):
    """Dzieli tekst na dwa adresy i poprawia ich format"""
    if not tekst:
        return None
    
    # Usuń znaki interpunkcyjne i popraw błędy
    tekst = re.sub(r'[^\w\s]', '', tekst.lower())
    tekst = popraw_adres(tekst)
    
    # Spróbuj podzielić na dwa adresy
    separatory = [
        r'\s+do\s+',
        r'\s+i\s+',
        r'\s+oraz\s+',
        r'\s+a\s+',
        r'\s+następnie\s+',
        r'\s+potem\s+'
    ]
    
    for separator in separatory:
        if re.search(separator, tekst):
            adresy = re.split(separator, tekst, maxsplit=1)
            if len(adresy) == 2:
                return [a.strip() for a in adresy]
    
    # Jeśli nie znaleziono separatora, podziel na pierwsze dwa wyrazy
    wyrazy = tekst.split()
    if len(wyrazy) >= 2:
        # Spróbuj znaleźć naturalny podział (np. po nazwie miasta)
        for i in range(1, len(wyrazy)):
            pierwszy = ' '.join(wyrazy[:i])
            drugi = ' '.join(wyrazy[i:])
            if len(pierwszy) > 3 and len(drugi) > 3:  # Minimalna długość adresu
                return [pierwszy, drugi]
    
    return None

def oblicz_odleglosc(adres1, adres2):
    """Oblicza odległość między dwoma adresami używając Google Maps API"""
    try:
        print(f"\n🔍 Szukam trasy z: '{adres1}' do '{adres2}'...")
        
        # Geokodowanie adresów
        geocode1 = gmaps.geocode(f"{adres1}, Polska")
        geocode2 = gmaps.geocode(f"{adres2}, Polska")
        
        if not geocode1:
            print(f"❌ Nie znaleziono adresu: {adres1}")
            return
        if not geocode2:
            print(f"❌ Nie znaleziono adresu: {adres2}")
            return
            
        # Pobierz pełne adresy
        pelny_adres1 = geocode1[0]['formatted_address']
        pelny_adres2 = geocode2[0]['formatted_address']
        
        print(f"\n📍 Adres startowy: {pelny_adres1}")
        print(f"📍 Adres docelowy: {pelny_adres2}")
        
        # Oblicz odległość
        wynik = gmaps.distance_matrix(
            origins=pelny_adres1,
            destinations=pelny_adres2,
            mode='driving',
            language='pl',
            region='pl'
        )
        
        if wynik['status'] == 'OK':
            element = wynik['rows'][0]['elements'][0]
            if element['status'] == 'OK':
                print(f"\n📏 Odległość: {element['distance']['text']}")
                print(f"⏱️ Czas podróży: {element['duration']['text']}")
                
                # Dodatkowe informacje o trasie
                trasa = gmaps.directions(pelny_adres1, pelny_adres2, mode="driving")
                if trasa:
                    kroki = trasa[0]['legs'][0]['steps']
                    print("\n🗺️ Główne etapy podróży:")
                    for i, krok in enumerate(kroki[:3], 1):  # Pierwsze 3 kroki
                        instrukcja = re.sub('<[^<]+?>', '', krok['html_instructions'])
                        print(f" {i}. {instrukcja} ({krok['distance']['text']})")
                    if len(kroki) > 3:
                        print(f" ...i kolejne {len(kroki)-3} etapów")
            else:
                print("❌ Nie można obliczyć trasy między podanymi adresami")
        else:
            print("❌ Błąd w zapytaniu do Google Maps API")
            
    except Exception as e:
        print(f"❌ Wystąpił błąd: {str(e)}")

def main():
    """Główna funkcja programu"""
    print("\n" + "="*50)
    print("🗺️  NAWIGACJA GŁOSOWA - INSTRUKCJA:")
    print("="*50)
    print("1. Podaj dwa adresy w jednej wypowiedzi")
    print("   Przykłady:")
    print("   - 'Ulica Długa 5 Warszawa do Aleja Krakowska 20 Pruszków'")
    print("   - 'Kraków i Wrocław'")
    print("   - 'Plac Defilad 1 Warszawa następnie Gdańsk'")
    print("2. Możesz powiedzieć 'koniec' aby zakończyć nagrywanie")
    print("3. Nagrywanie zakończy się też automatycznie po ciszy")
    print("="*50 + "\n")
    
    while True:
        input("Naciśnij Enter aby rozpocząć nagrywanie...")
        
        sciezka = nagraj_audio()
        if not sciezka:
            continue
            
        tekst = rozpoznaj_mowe(sciezka)
        if not tekst:
            continue
            
        adresy = przetworz_tekst(tekst)
        if adresy and len(adresy) == 2:
            adres1, adres2 = adresy
            oblicz_odleglosc(adres1, adres2)
        else:
            print("\n❌ Nie rozpoznano poprawnie dwóch adresów. Spróbuj ponownie.")
            print("Przykład: 'Ulica Długa 5 Warszawa do Aleja Krakowska 20 Pruszków'\n")
        
        decyzja = input("\nCzy chcesz spróbować jeszcze raz? (t/n): ").lower()
        if decyzja != 't':
            print("\nDziękuję za skorzystanie z programu! Do widzenia!")
            break

if __name__ == "__main__":
    main()
