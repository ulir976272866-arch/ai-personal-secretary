import requests

def test_nominatim(address):
    headers = { 'User-Agent': 'AIPersonalSecretary/1.0' }
    url = f"https://nominatim.openstreetmap.org/search?q={address}&format=json&limit=1"
    print(f"URL: {url}")
    res = requests.get(url, headers=headers, timeout=5).json()
    print(f"Response: {res}")
    if res and len(res) > 0:
        return float(res[0]['lat']), float(res[0]['lon'])
    return None, None

addr = "110台灣台北市信義區安康里松仁路101號"
print(test_nominatim(addr))
