import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_lat_lng(address):
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={address}&key={api_key}"
    print(f"URL: {url}")
    res = requests.get(url).json()
    print(f"Response: {res}")
    if res['status'] == 'OK':
        loc = res['results'][0]['geometry']['location']
        return loc['lat'], loc['lng']
    return None, None

addr = "112台灣台北市北投區尊賢里實踐街47號"
print(get_lat_lng(addr))
