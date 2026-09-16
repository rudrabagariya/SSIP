import os
import requests
from bs4 import BeautifulSoup
import re
import urllib.parse

products = {
    1001: "Balaji Banana Wafer Mast Mari packet",
    1002: "Balaji Crunchem Simply Salted packet",
    1003: "Balaji Gippi Tornado packet",
    1004: "Chana Dal Balaji namkeen packet",
    1005: "Funne Balaji packet",
    1006: "Gokul Nylon Gathiya packet",
    1007: "Gopal Masala Cup namkeen packet",
    1008: "Mug Dal Balaji packet",
    1009: "Sticks Gopal namkeen packet",
    1010: "Wheels Balaji snacks packet"
}

os.makedirs("images", exist_ok=True)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
}

for barcode, name in products.items():
    print(f"Searching for {name}...")
    try:
        url = f"https://www.bing.com/images/search?q={urllib.parse.quote(name)}"
        resp = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Bing images usually have a 'm' attribute containing the media url
        downloaded = False
        for a in soup.find_all("a", class_="iusc"):
            m = a.get("m")
            if m:
                m_dict = eval(m.replace("true", "True").replace("false", "False"))
                img_url = m_dict.get("murl")
                if img_url:
                    try:
                        print(f"Attempting {img_url}")
                        img_resp = requests.get(img_url, headers=headers, timeout=5)
                        if img_resp.status_code == 200:
                            with open(f"images/{barcode}.jpg", "wb") as f:
                                f.write(img_resp.content)
                            print(f"Downloaded {barcode}.jpg successfully.")
                            downloaded = True
                            break
                    except:
                        pass
        if not downloaded:
            print(f"Failed to find image for {name}")
    except Exception as e:
        print(f"Search failed for {name}: {e}")
