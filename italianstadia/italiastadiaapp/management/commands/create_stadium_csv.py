import csv
from django.core.management.base import BaseCommand
# Sostituisci 'stadium_app' con il nome reale della tua app Django
from italiastadiaapp.models import Stadium 

class Command(BaseCommand):
    help = 'Esporta tutti i dati degli stadi in un file CSV'

    def handle(self, *args, **options):
        # Definiamo il percorso di salvataggio
        file_path = 'stadiums.csv'
        
        self.stdout.write(self.style.NOTICE(f"Inizio esportazione in {file_path}..."))

        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            
            # Intestazione del file CSV
            w.writerow([
                'name', 'capacity', 'address', 'year_of_construction', 'city', 
                'owner_raw', 'ownership', 'slug', 'stadium_type', 'surface', 
                'architect', 'latitude', 'longitude'
            ])
            
            # Scrittura dei dati
            stadiums = Stadium.objects.select_related('city').all()
            for s in stadiums:
                w.writerow([
                    s.name,
                    s.capacity,
                    s.address,
                    s.year_of_construction,
                    s.city.name if s.city else '',  # Cambia 'name' se il modello City usa un altro campo
                    s.owner_raw,
                    s.ownership,
                    s.slug,
                    s.stadium_type,
                    s.surface,
                    s.architect,
                    s.latitude,
                    s.longitude
                ])
                
        self.stdout.write(self.style.SUCCESS('Esportazione completata con successo!'))
