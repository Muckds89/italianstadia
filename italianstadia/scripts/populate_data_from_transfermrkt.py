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

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
import re
import logging
import time

# Set up Django environment
project_path = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
sys.path.append(project_path)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "italianstadia.settings")
django.setup()

from italiastadiaapp.models import City, Stadium, Team

# Check if 'scraping.log' exists and delete it
log_file = 'scraping_tranfermrkt.log'
if os.path.exists(log_file):
    os.remove(log_file)
    print(f"{log_file} has been deleted.")
else:
    print(f"{log_file} does not exist.")

# Configure logging
logging.basicConfig(
    filename='scraping_tranfermrkt.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Load JSON data
with open('transfermrkt_urls.json') as f:
    data = json.load(f)

def scrape_city(url):
    """Scrape city data from Wikipedia."""
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    try:
        # Example: finding the city name and population from the Wikipedia page
        name = soup.find('h1', {'id': 'firstHeading'}).text
        population_text = soup.find(string="Population").find_next().text
        population_cleaned = re.sub(r'\D', '', population_text)  # Remove non-digit characters
        population = int(population_cleaned)
        country = soup.find(string="Country").find_next().text
        
        city, created = City.objects.get_or_create(name=name, defaults={
            'population': population,
            'country': country
        })
        if created:
            logging.info(f"Created new City: {name}")
        else:
            logging.info(f"City {name} already exists")
        return city
    except Exception as e:
        logging.error(f"Error scraping city {url}: {e}")



def scrape_stadium(url, city):
    """Scrape stadium data from Transfermarkt using Selenium."""
    # Set up Selenium WebDriver with WebDriver Manager
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)
    
    driver.get(url)
    time.sleep(2)  # Allow time for the page to load

    try:
        # Check for multiple iframes and iterate through each
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        consent_given = False
        for iframe in iframes:
            driver.switch_to.frame(iframe)
            logging.info("Switched to iframe.")
            
            try:
                # Try clicking the "Accept & continue" button
                accept_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept & continue')]"))
                )
                accept_button.click()
                logging.info("Accepted consent in iframe.")
                consent_given = True
                driver.switch_to.default_content()  # Switch back to main content after clicking
                time.sleep(2)  # Allow time for the page to proceed
                break
            except (TimeoutException, NoSuchElementException):
                logging.info("Consent button not found in this iframe.")
                driver.switch_to.default_content()  # Go back to main content to try the next iframe

        if not consent_given:
            logging.info("No consent popup found, or it was already dismissed.")

        # Extract the stadium name from the "Name of stadium" row
        name_row = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//th[text()='Name of stadium:']"))
        )
        name = name_row.find_element(By.XPATH, "following-sibling::td").text.strip()

        # Scroll to "Total capacity" to ensure it loads
        capacity_row = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//th[text()='Total capacity:']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", capacity_row)
        time.sleep(1)  # Allow time after scrolling

        # Once the row is located, find the next <td> element
        capacity_text = capacity_row.find_element(By.XPATH, "following-sibling::td").text.strip()
        
        # Check if capacity_text is not empty
        if not capacity_text:
            logging.error(f"Total capacity field is empty for stadium at {url}")
            return None
        
        # Process the capacity text if it is not empty
        capacity = int(re.sub(r'\D', '', capacity_text))  # Remove any non-numeric characters

         # Extract the year of construction using "Built:"
        try:
            built_row = driver.find_element(By.XPATH, "//th[text()='Built:']")
            year_of_construction_text = built_row.find_element(By.XPATH, "following-sibling::td").text.strip()
            year_of_construction = int(year_of_construction_text) if year_of_construction_text.isdigit() else None
        except NoSuchElementException:
            logging.info("Year of construction not found.")
            year_of_construction = None  # Set to None if not found

        # Optional: extract other fields if needed, such as address
        address = "Unknown"  # Replace with actual extraction if needed

        driver.quit()

        # Store data in the database
        stadium, created = Stadium.objects.get_or_create(name=name, city=city, defaults={
            'capacity': capacity,
            'address': address,
            'year_of_construction': year_of_construction
        })
        if created:
            logging.info(f"Created new Stadium: {name}")
        else:
            logging.info(f"Stadium {name} already exists")
        return stadium
    except TimeoutException:
        logging.error(f"Timed out waiting for 'Total capacity' field at {url}")
    except Exception as e:
        logging.error(f"Error scraping stadium {url}: {e}")
    finally:
        driver.quit()

from datetime import datetime

def scrape_average_attendance(attendance_url):
    """Scrape average attendance for the current season from a team's attendance page."""
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)

    driver.get(attendance_url)
    time.sleep(3)  # Allow time for the page to load

    try:
        # Locate the row for the 2024/25 season and target the last <td class="rechts"> element
        attendance_row = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//tr[td[contains(text(), '24/25')]]"))
        )

        # Scroll to the row to ensure it loads
        driver.execute_script("arguments[0].scrollIntoView(true);", attendance_row)
        time.sleep(1)  # Wait a moment after scrolling

        # Use JavaScript to get the text of the last <td class="rechts"> element
        attendance_text = driver.execute_script(
            "return arguments[0].querySelectorAll('.rechts')[arguments[0].querySelectorAll('.rechts').length - 1].textContent;",
            attendance_row
        ).strip()

        if attendance_text:
            average_attendance = int(attendance_text.replace(",", ""))
            logging.info(f"Extracted average attendance: {average_attendance}")
        else:
            logging.error("Attendance data is empty.")
            average_attendance = None
    except Exception as e:
        logging.error(f"Error scraping attendance data: {e}")
        average_attendance = None
    finally:
        driver.quit()

    return average_attendance

def scrape_team(team_name, team_url, attendance_url, stadium, city):
    """Scrape team data from Transfermarkt using Selenium."""
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service)

    driver.get(team_url)
    time.sleep(2)  # Allow time for the page to load

    manager_name = None  # Initialize manager_name to avoid scoping issues
    try:
        # Handle consent popup if present
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for iframe in iframes:
            driver.switch_to.frame(iframe)
            try:
                accept_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept & continue')]"))
                )
                accept_button.click()
                logging.info("Accepted consent in iframe.")
                driver.switch_to.default_content()
                time.sleep(2)  # Allow time for the page to proceed
                break
            except (TimeoutException, NoSuchElementException):
                driver.switch_to.default_content()  # Go back to main content to try the next iframe

        # Extract Italian Champion titles (example)
        try:
            italian_champion_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//a[@title='Italian Champion']/span[@class='data-header__success-number']"))
            )
            italian_champion_text = italian_champion_element.text.strip()
            italian_champion_titles = int(italian_champion_text.replace(",", "")) if italian_champion_text.isdigit() else 0
            logging.info(f"Italian Champion titles: {italian_champion_titles}")
        except NoSuchElementException:
            italian_champion_titles = 0
            
        # Extract the founded date
        try:
            founded_element = driver.find_element(By.XPATH, "//span[@itemprop='foundingDate']")
            founded_text = founded_element.text.strip()
            founded = datetime.strptime(founded_text, "%b %d, %Y").date()
            logging.info(f"Extracted founded date: {founded}")
        except NoSuchElementException:
            logging.info("Founded year not found; setting to None.")
            founded = None

        # Extract the "tier" information based on the correct structure
        try:
            tier_element = driver.find_element(By.XPATH, "//span[@class='data-header__content']/a[contains(@href, '/wettbewerb/')]")
            tier_text = tier_element.text.strip()
            logging.info(f"Extracted tier text: {tier_text}")

            # Determine tier number based on extracted text
            if "First Tier" in tier_text:
                tier = 1
            elif "Second Tier" in tier_text:
                tier = 2
            elif "Third Tier" in tier_text:
                tier = 3
            elif "Fourth Tier" in tier_text:
                tier = 4
            else:
                logging.error(f"Unrecognized tier text '{tier_text}' for team at {team_url}")
                return None
        except NoSuchElementException:
            logging.error("Tier information not found.")
            return None
        
        driver.quit()

        # Scrape average attendance from attendance page
        average_attendance = scrape_average_attendance(attendance_url)

        # Save team data to the database
        team, created = Team.objects.get_or_create(name=team_name, city=city, stadium=stadium, defaults={
            'founded': founded,
            'tier': tier,
            'num_of_titles': italian_champion_titles,
            'manager': manager_name,
            'average_attendance': average_attendance,
        })

        if created:
            logging.info(f"Created new Team: {team_name}")
        else:
            logging.info(f"Team {team_name} already exists")

        return team
    except TimeoutException:
        logging.error(f"Timed out waiting for 'Italian Champion' field at {team_url}")
    except Exception as e:
        logging.error(f"Error scraping team at {team_url}: {e}")
    finally:
        driver.quit()


# Main script execution
for city_url in data['cities']:
    city = scrape_city(city_url)

for stadium_data in data['stadia']:
    for stadium_url in stadium_data.values():
        stadium = scrape_stadium(stadium_url, city)

for team_data in data['teams']:
    team_name = team_data.get('name')
    team_url = team_data.get('transfermarkt_url')
    attendance_url = team_data.get('transfermarkt_url_attendace')
    
    if team_name and team_url:
        scrape_team(team_name, team_url, attendance_url, stadium, city)
    else:
        logging.error(f"Missing name or URL for team data: {team_data}")
