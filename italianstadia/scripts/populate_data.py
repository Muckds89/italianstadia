import json
import requests
from bs4 import BeautifulSoup
import django
import os
import sys
import logging
import re
from datetime import datetime
from django.db.utils import IntegrityError

# Set up Django environment
project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(project_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "italianstadia.settings")
django.setup()

from italiastadiaapp.models import City, Stadium, Team

# Configure logging
logging.basicConfig(
    filename='scraping.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def clean_population(population_str):
    """Convert population string to a numerical value."""
    population_str = population_str.replace('\xa0', ' ').replace(',', '')
    match = re.search(r'(\d+(\.\d+)?)', population_str)
    if match:
        population_number = float(match.group(1))
        if 'million' in population_str:
            population_number *= 1_000_000
        elif 'billion' in population_str:
            population_number *= 1_000_000_000
        return int(population_number)
    raise ValueError("Cannot convert population string to number")

def clean_capacity(capacity_str):
    """Extract numerical capacity from string."""
    capacity_str = capacity_str.replace(',', '').split(' ')[0]
    match = re.search(r'(\d+)', capacity_str)
    if match:
        return int(match.group(1))
    raise ValueError("Cannot convert capacity string to number")

def clean_year_of_construction(year_str):
    """Extract year from string."""
    match = re.search(r'(\d{4})', year_str)
    if match:
        return int(match.group(1))
    raise ValueError("Cannot convert year string to number")

def extract_average_attendance_from_transfermarkt(url):
    """Extract average attendance from Transfermarkt for the given URL."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    
    # Log the URL
    print(f"Fetching URL: {url}")
    
    # Check if the request was successful
    if response.status_code == 404:
        raise Exception(f"Page not found (404 error) for URL: {url}")
    elif response.status_code != 200:
        raise Exception(f"Failed to fetch the page, status code: {response.status_code} for URL: {url}")

    soup = BeautifulSoup(response.content, 'html.parser')

    table = soup.find('table', class_='items')

    # If table is None, log the content and raise an error
    if table is None:
        with open("debug.html", "w", encoding="utf-8") as file:
            file.write(response.text)
        raise Exception(f"Failed to find the table with class 'items'. Check debug.html for the page content from URL: {url}")

    latest_season_data = None
    for row in table.tbody.find_all('tr'):
        season = row.find_all('td')[0].text.strip()
        if season == '23/24':
            latest_season_data = {
                "Stagione": season,
                "Competizione": row.find_all('td')[1].text.strip(),
                "Partite": row.find_all('td')[2].text.strip(),
                "Esaurito": row.find_all('td')[3].text.strip(),
                "Spett.": row.find_all('td')[4].text.strip(),
                "Media": row.find_all('td')[5].text.strip()
            }
            break

    # If no data found for the specified season, raise an error
    if latest_season_data is None:
        raise Exception("No data found for the 23/24 season.")

    # Convert 'Media' from string to float, replacing comma with period
    average_attendance = float(latest_season_data['Media'].replace('.', '').replace(',', '.'))

    return average_attendance

def extract_info_city(soup):
    info_box = soup.find('table', {'class': 'infobox'})
    rows = info_box.find_all('tr')

    country = None
    population = None

    for row in rows:
        header = row.find('th')
        if header:
            header_text = header.text.strip().lower()
            td = row.find('td')
            if td:
                if 'country' in header_text:
                    country = td.text.strip()
                if 'population' in header_text:
                    population = td.text.strip()
                    # Break the loop if both country and population are found
                    if country and population:
                        break
    
    if not population:
        # Fallback method to find population in the text content
        population_text = soup.find(text=lambda t: "population of about" in t.lower())
        if population_text:
            population = population_text.split("population of about")[1].split(",")[0].strip()

    if not population:
        raise ValueError("Population data not found")

    population = clean_population(population)

    return country, population

def extract_info_stadium(soup):
    info_box = soup.find('table', {'class': 'infobox'})
    rows = info_box.find_all('tr')

    capacity = None
    address = None
    year_of_construction = None
    average_attendance = None
    city_name = None

    for row in rows:
        header = row.find('th')
        if header:
            header_text = header.text.strip().lower()
            td = row.find('td')
            if td:
                if 'capacity' in header_text:
                    capacity = clean_capacity(td.text.strip())
                if 'address' in header_text:
                    address = td.text.strip()
                if 'opened' in header_text:
                    year_of_construction = clean_year_of_construction(td.text.strip())
                if 'average attendance' in header_text:
                    average_attendance = td.text.strip()
                if 'location' in header_text:
                    location_text = td.text.strip()
                    # The city name can be extracted from the location text
                    if ',' in location_text:
                        city_name = location_text.split(',')[0].strip()
                    else:
                        city_name = location_text

    return capacity, address, year_of_construction, average_attendance, city_name

def extract_info_team(soup):
    # First try to find data within the infobox vcard
    info_box = soup.find('table', {'class': 'infobox vcard'})
    founded = None
    tier = None
    stadium_name = None
    manager = None
    city_name = None

    if info_box:
        rows = info_box.find_all('tr')
        for row in rows:
            header = row.find('th', {'class': 'infobox-label'})
            if header:
                header_text = header.text.strip().lower()
                td = row.find('td', {'class': 'infobox-data'})
                if td:
                    logging.info(f"Extracting data for header: {header_text}")
                    if 'founded' in header_text:
                        founded = td.text.strip()
                    if 'tier' in header_text:
                        tier = td.text.strip()
                    if 'ground' in header_text:
                        stadium_name = td.text.strip()
                    if 'manager' in header_text:
                        manager = td.text.strip()
                    if 'location' in header_text:
                        location_text = td.text.strip()
                        if ',' in location_text:
                            city_name = location_text.split(',')[0].strip()
                        else:
                            city_name = location_text

    if not city_name:
        # If city name is not found in the infobox, search within mw-body-content
        body_content = soup.find('div', {'id': 'bodyContent'})
        if body_content:
            paragraphs = body_content.find_all('p')
            for paragraph in paragraphs:
                text = paragraph.text.strip().lower()
                if 'based in' in text:
                    city_name_match = re.search(r'based in ([^,.\n]+)', text)
                    if city_name_match:
                        city_name = city_name_match.group(1).strip()
                        break

    logging.info(f"Extracted team info - Founded: {founded}, Tier: {tier}, Stadium: {stadium_name}, Manager: {manager}, City: {city_name}")
    return founded, tier, stadium_name, manager, city_name

def scrape_city(url):
    logging.info(f"Scraping city data from: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    name = soup.find('h1').text.strip()
    
    try:
        country, population = extract_info_city(soup)
    except ValueError as e:
        logging.error(f"Error scraping population for {name}: {e}")
        return
    
    logging.info(f"City data - Name: {name}, Population: {population}, Country: {country}")
    
    city, created = City.objects.get_or_create(name=name, defaults={'population': population, 'country': country})
    if not created:
        city.population = population
        city.country = country
        city.save()
    logging.info(f"City {'created' if created else 'updated'}: {city}")

def scrape_stadium(wikipedia_url, transfermarkt_url):
    logging.info(f"Scraping stadium data from: {wikipedia_url}")
    response = requests.get(wikipedia_url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    name = soup.find('h1').text.strip()
    try:
        capacity, address, year_of_construction, average_attendance, city_name = extract_info_stadium(soup)
    except ValueError as e:
        logging.error(f"Error scraping data for {name}: {e}")
        return

    if not average_attendance:
        try:
            average_attendance = extract_average_attendance_from_transfermarkt(transfermarkt_url)
        except ValueError as e:
            logging.error(f"Error scraping average attendance for {name} from Transfermarkt: {e}")
            average_attendance = None
    
    city = City.objects.get(name=city_name)
    logging.info(f"Stadium data - Name: {name}, Capacity: {capacity}, Address: {address}, Year of Construction: {year_of_construction}, Average Attendance: {average_attendance}, City: {city}")
    
    stadium, created = Stadium.objects.get_or_create(name=name, defaults={
        'capacity': capacity,
        'address': address,
        'year_of_construction': year_of_construction,
        'average_attendance': average_attendance,
        'city': city
    })
    if not created:
        stadium.capacity = capacity
        stadium.address = address
        stadium.year_of_construction = year_of_construction
        stadium.average_attendance = average_attendance
        stadium.save()
    logging.info(f"Stadium {'created' if created else 'updated'}: {stadium}")

def scrape_team(url):
    logging.info(f"Scraping team data from: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')

    name = soup.find('h1').text.strip()
    logging.info(f"Team name extracted: {name}")

    founded, tier, stadium_name, manager, city_name = extract_info_team(soup)

    if not stadium_name:
        logging.error(f"Stadium information not found for team: {name}")
        return

    if not city_name:
        logging.error(f"City information not found for team: {name}")
        return

    logging.info(f"Extracted data - Founded: {founded}, Tier: {tier}, Stadium: {stadium_name}, Manager: {manager}, City: {city_name}")

    # Convert tier to appropriate integer based on TIER_CHOICES
    tier_mapping = {
        'Serie A': 1,
        'Serie B': 2,
        'Serie C': 3,
        'Serie D': 4,
    }
    # Check if tier is available, and map it; otherwise, assign a default or skip
    if tier:
        tier = tier_mapping.get(tier, None)
        if not tier:
            logging.warning(f"Tier information unrecognized for team: {name}. Setting tier to default value 1.")
            tier = 1  # Assign a default value, such as 0, indicating unknown tier
    else:
        logging.warning(f"Tier information missing for team: {name}. Setting tier to default value 1.")
        tier = 1  # Assign a default value when no tier is found


    # Clean up the founded date string using regex to extract only the date part
    founded_date = None
    if founded:
        # Use regex to extract the first valid date from the string
        date_match = re.search(r'\d{1,2}\s\w+\s\d{4}', founded)
        if date_match:
            founded_clean = date_match.group(0)
            logging.info(f"Cleaned founded date: {founded_clean}")
            try:
                founded_date = datetime.strptime(founded_clean, "%d %B %Y").date()
            except ValueError:
                logging.error(f"Could not convert founded date for team: {name}, cleaned value was: {founded_clean}")
                return
        else:
            logging.error(f"No valid date found in founded information for team: {name}, raw value was: {founded}")
            return

    if not founded_date:
        logging.error(f"Founded date is required for team: {name}")
        return
    
    # Handle the case of alternative names for the stadium
    if stadium_name == "Stadio Giuseppe Meazza":
        stadium_name = "San Siro"  # Automatically convert to the preferred name

    # Get the stadium object
    try:
        stadium = Stadium.objects.get(name__icontains=stadium_name)
    except Stadium.DoesNotExist:
        logging.error(f"Stadium not found: {stadium_name}")
        return

    # Get the city object
    try:
        city = City.objects.get(name__iexact=city_name)
    except City.DoesNotExist:
        logging.error(f"City not found: {city_name}")
        return

    logging.info(f"Team data - Name: {name}, Founded: {founded_date}, Tier: {tier}, Stadium: {stadium}, Manager: {manager}, City: {city}")

    try:
        team, created = Team.objects.get_or_create(name=name, defaults={
            'founded': founded_date,
            'tier': tier,
            'stadium': stadium,
            'manager': manager,
            'city': city,
            'num_of_titles': 0  # Default value for num_of_titles
        })
        if not created:
            team.founded = founded_date
            team.tier = tier
            team.stadium = stadium
            team.manager = manager
            team.city = city
            team.save()
        logging.info(f"Team {'created' if created else 'updated'}: {team}")
    except IntegrityError as e:
        logging.error(f"Integrity error while creating/updating team {name}: {e}")
        
def populate_data():
    with open('data_urls.json') as f:
        data = json.load(f)

    print("json loaded")
    if False:
        for city_url in data['cities']:
            scrape_city(city_url)
        
        for stadium_data in data['stadia']:
            scrape_stadium(stadium_data['wikipedia'], stadium_data['transfermarkt'])
    
    for team in data['teams']:
        team_name = team['name']
        team_url = team['url']
        print(f"Team: {team_name}, URL: {team_url}")
        scrape_team(team_url)

if __name__ == '__main__':
    populate_data()

