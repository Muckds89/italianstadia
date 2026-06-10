# EuropeanStadia

EuropeanStadia is a Django project for collecting, storing, and presenting information about European football stadiums.

The intended final product is a website with stadium resources, including an interactive map where users can explore European stadiums and view details gathered from public web sources such as Wikipedia and Transfermarkt.

## Project purpose

This project appears to have two main goals:

1. Scrape or collect stadium and football-club information from the web.
2. Populate a Django database so the data can be displayed through a website.

The main data sources appear to be:

- Wikipedia
- Transfermarkt

## Project structure

```text
EuropeanSTADIA/
├── Europeanstadia/                 # Main Django project configuration package
│   ├── __init__.py
│   ├── asgi.py                    # ASGI entry point
│   ├── settings.py                # Django settings
│   ├── urls.py                    # Root URL routing
│   └── wsgi.py                    # WSGI entry point
│
├── italiastadiaapp/               # Main Django application
│   ├── migrations/                # Database migration files
│   ├── templates/                 # HTML templates
│   ├── __init__.py
│   ├── admin.py                   # Django admin configuration
│   ├── apps.py                    # App configuration
│   ├── models.py                  # Database models
│   ├── tests.py                   # Tests
│   ├── urls.py                    # App-specific URL routing
│   └── views.py                   # View logic for rendering pages / API responses
│
├── scripts/                       # Data scraping and database population scripts
│   ├── populate_data_from_transfermrkt.py
│   └── populate_data.py
│
├── data_urls.json                 # Stored source URLs or scraped input data
├── transfermrkt_urls.json         # Transfermarkt URLs used by scraping scripts
├── db.sqlite3                     # Local SQLite database
├── manage.py                      # Django management entry point
├── scraping.log                   # Scraping log file
├── scraping_transfermrkt.log      # Transfermarkt scraping log file
├── my_django_env/                 # Local Python virtual environment
├── .gitignore
└── pyvenv.cfg