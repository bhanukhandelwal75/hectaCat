import googlemaps
import random
import pandas as pd
import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import requests
import math
from collections import defaultdict
import re
import json
from hectalogging import log
from dboperations import insert_data
from config import Config,generate_key
import geopandas as gpd
from shapely.geometry import Point, shape


config=Config()
generate_key()
GEMINI_API_KEY=config.get_decrypted_key('GEMINI_API_KEY')
MAPS_API_KEY=config.get_decrypted_key('MAPS_API_KEY')
genai.configure(api_key=GEMINI_API_KEY)  # Gemini Flash API key
model = genai.GenerativeModel("gemini-1.5-flash")

# Geocoding API key for Google Maps
gmaps = googlemaps.Client(key=MAPS_API_KEY)
def title_case(text):
    return " ".join(word.capitalize() for word in text.split())


def clean_address(address):
    super_clean_address="" #sometime it throw error so paassing it empty
    property_type_ind=None
    """
    Function to clean and condense the provided address.
    """
    
    prompt = (
        f"Your task is to clean and structure the following address into a single-line format for easy identification and navigation.\n"
        f"---\n"
        f"### **Rules for Cleaning:**\n"
        f"- **DO NOT** add extra words like 'Formatted Address:' or 'Clean Address:' in the response.\n"
        f"- **DO NOT** include PIN codes, state names, administrative divisions like tehsil, district, taluka, village, or borrower's name.\n"
        f"- **KEEP ONLY ESSENTIAL IDENTIFIERS** needed to locate the property. Ensure no important details are removed.\n"
        f"- **Keep Name or Location Name of Village/Vilage and Taluk/Taluka,as it is important for me. Dont leave in final Cleaned address.\n"
        f"- Please Before finalizing, verify that intermediate locations like sub-cities or talukas are not removed.\n"
        f"- If a House No. is present in the address (e.g., House No.125, Municipal House No.10, etc.), then DO NOT include Survey No., Plot No., Khasra No., or similar land identifiers in the final cleaned address. If Municipial House No.' is explicitly mentioned, then remove 'Survey No.' completely from the final address.Do not include Survey No. if 'House No.' is present.\n"
        f"- If 'Gala No.', 'Shop No.', or any commercial unit identifier is present in the address, it must be retained in the final cleaned address.\n."
        f"- The address must include identifiers like Plot No, Survey No, SF, Gat No, etc., if present.\n"
        f"\n"
        f"### **Rules for Different Property Types:**\n"
        f"-Dont Miss floor in clean address,as it is important to find address by sales person and buyer.\n" 
        f"- **FLATS / APARTMENTS** → Include: **Flat No, Floor, Block No.(If given), Phase(If given), Building Name, Sub-localities name(if given), Locality, City** in the final cleaned address. Remove: **Survey No, Khasra No, Plot No.**\n"
        f"- **PLOTS / HOUSES / ROW HOUSES** → Include: **Plot No, Block No, House No, Locality, City**. Keep identifiers like 'Plot No' and 'Block No' if given. If only khewat no ,khata no is given in address then take in cleaned address.\n"
        f"- For agricultural land and plot there is khasra and khatoni no ,use your intelligence whether to keep it or not.\n"
        f"- Dont miss anything which led to confusion.\n"
        f"- **COMMERCIAL PROPERTIES** → Include: **Shop No, Floor, Building Name, Market Name, Locality, City**.\n"
        f"- **VACANT LAND** → Include: **Plot No, Block No, Locality, City**. Remove extra legal terms but **keep location-relevant identifiers.**\n"
        f"- **FACTORY** → Include: **Plot No, Block No, Locality,District, City**. Remove extra legal terms but **keep location-relevant identifiers.**\n"
        f"\n"
        f"### **Additional Extraction:**\n"
        f"- Extract the **Area** of the property (e.g., square feet or square meters or square Yards or Acres), and store it as a variable. If it is carpet area, mark it as **CA**, if built-up area, mark it as **BUA**.\n"
        f"- Identify the **Locality** (if given) and extract it separately.\n"
        f"- If the **Building Name or Society Name** is mentioned (for Flats, Apartments or Villas), it must be included naturally in the cleaned address.\n"
        f"- Additionally, create a new variable called **Super Clean Address**, which only includes: Building Name (if given), Society Name (if given), Area Name(s), Village name(if given), Locality, City, State. Use your intellegence to give these details in that order right.This will be used for geolocation purposes. Make sure not to miss Building name if given.\n"
        f"- Use AI to determine and classify the **Property Type** as one of the following:\n"
        f"  - Residential Flat\n"
        f"  - Residential House/Building\n"
        f"  - Residential Plot\n"
        f"  - Vacant Land\n"
        f"  - Commercial Shop/Retail Space\n"
        f"  - Factory Land\n"
        f"\n"
        f"---\n"
        f"**Address to Clean:** {address}\n"
        f"Provide ONLY the cleaned address in a structured format without unnecessary symbols or formatting."

    )


    response_text = ""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            
            response = model.generate_content(prompt,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH, 
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH
                })
            response_text = response.text.strip()
            if response_text:
              break
        except Exception as e:
            log("ERROR",f"An error occurred in gemini: {e}")
            time.sleep(5)

    if not response_text:
        cleaned_address = title_case(address.strip())
        super_clean_address = title_case(cleaned_address)
        return cleaned_address, "", super_clean_address, "", super_clean_address, "Residential Property"
        
    Area,MicroMarket,buildingname,super_clean_address, property_type_ind = "","","","",""    
    
    cleaned_lines = []
    lines = response_text.strip().split("\n")
    for line in lines:
        if ( "None-mentioned".lower()  in line.lower() or "Not specified".lower()  in line.lower() or "None specified".lower() in line.lower() or "NO need to mention".lower()  in line.lower() ):
            continue
        if "Area".lower() in line.lower() :
            Area = line.split(":",1)[-1].strip()
            Area = Area.strip('*').strip()
            
        elif "Locality".lower() in line.lower():
            cleaned = re.sub(r"\*+", "", line.split(":", 1)[-1])
            MicroMarket = cleaned.strip()
        elif "building".lower() in line.lower():
            buildingname = line.split(":",1)[-1].strip()  
        elif "Super Clean Address".lower() in line.lower():
            cleaned = re.sub(r"\*+", "", line.split(":", 1)[-1])
            super_clean_address = title_case(cleaned.strip())
        elif "Property Type".lower() in line.lower():
            cleaned = re.sub(r"\*+", "", line.split(":", 1)[-1])
            property_type_ind = cleaned.strip()        
        else:
            if not re.search(r"(?i)^.*Building\s+Name\s+Or\s+Society\s+Name\s*:\s*(Not\s*(Specified|Mentioned|Available)|NA)", line):
                cleaned_lines.append(line)
    
    
    cleaned_address = title_case(" ".join(cleaned_lines))
    cleaned_address = re.sub(r'\s*,?\s*(Building\s+(?:Name\s*(?:/|Or)?\s*Society\s+Name|Name|Society\s+Name))\s*:\s*.*$', '', cleaned_address, flags=re.IGNORECASE)
    cleaned_address = re.sub(r'\s*,?\s*Building Name/society Name:.*$', '', cleaned_address, flags=re.IGNORECASE)
    cleaned_address = re.sub(r'\b(?:village|vilage|taluk|taluka|gaon|gram)\b\s*', '', cleaned_address, flags=re.IGNORECASE)
    cleaned_address = re.sub(r'\s*,\s*', ', ', cleaned_address).strip()
 
    if cleaned_address.strip() == "" :
        cleaned_address = title_case(lines[0].strip()) 

    if not super_clean_address:
        address_parts = cleaned_address.split(",")
        if len(address_parts) >= 2:
            super_clean_address = f"{title_case(address_parts[-2].strip())}, {title_case(address_parts[-1].strip())}"
        else:
            super_clean_address = title_case(cleaned_address.strip())
    if not MicroMarket:
        MicroMarket=super_clean_address    
            
    if not property_type_ind:
        address_lower = cleaned_address.lower()
        if 'f no' in address_lower or 'f.no' in address_lower or 'flat' in address_lower:
            property_type_ind = "Residential Flat"
        elif ('row house' in address_lower or 'house' in address_lower or 'house no' in address_lower or 'door' in address_lower) and \
             ('plot no' in address_lower or 'Sy No' in address_lower or 'survey no' in address_lower or 'Sy' in address_lower):
            property_type_ind = "Residential House/Building"
        elif any(keyword in address_lower for keyword in ['house', 'door', 'row house', 'house no', 'door no']):
            property_type_ind = "Residential House/Building"
        elif any(keyword in address_lower for keyword in ['plot', 'sy no', 'survey no', 'katha no', 'khasra']):
            property_type_ind = "Residential Plot"
        elif any(keyword in address_lower for keyword in ['door', 'asset no', 'house', 'row house']):
            property_type_ind = "Residential House/Building"
        elif 'bungalow' in address_lower:
            property_type_ind = "Residential Bungalow"
        elif 'farm' in address_lower:
            property_type_ind = "Residential Farm House"
        elif 'villa' in address_lower:
            property_type_ind = "Villa"
        elif 'office' in address_lower:
            property_type_ind = "Commercial Office Space"
        elif 'shop' in address_lower:
            property_type_ind = "Commercial Shop/Retail Space"
        elif 'warehouse' in address_lower:
            property_type_ind = "Warehouse"
        elif 'showroom' in address_lower:
            property_type_ind = "Commercial Showroom"
        elif 'land' in address_lower or 'vacant land' in address_lower:
            property_type_ind = "Land and Building"
        else:
            property_type_ind = "Residential Plot"  # Default fallback
    
               
    return cleaned_address, Area, MicroMarket, buildingname, super_clean_address, property_type_ind    




def determine_property_type(cleaned_address):
    """
    Function to determine the property type based on the cleaned address.
    """
    
    address_lower = cleaned_address.lower()

    if 'f no' in address_lower or 'f.no' in address_lower or 'flat' in address_lower:
        return "Residential Flat"
    if ('row house' in address_lower or 'house' in address_lower or 'house no' in address_lower or 'door' in address_lower) and ('plot no' in address_lower or 'Sy No' in address_lower or 'survey no' in address_lower or 'Sy' in address_lower):
        return "Residential House/Building"       
    
        
    if any(keyword in address_lower for keyword in ['house', 'door', 'row house', 'house no', 'door no']):
        return "Residential House/Building"
    
    

    
    
    if 'flat' in address_lower:
        return "Residential Flat"
    elif 'plot' in address_lower or 'sy no' in address_lower or 'survey no' in address_lower or 'katha no' in address_lower or 'khasra' in address_lower:
        return "Residential Plot"
    elif 'Door' in address_lower or 'asset no' in address_lower or 'house' in address_lower or 'row house' in address_lower:
        return "Residential House/Building"
    elif 'Bungalow' in address_lower:
        return "Residential Bungalow"
    elif 'farm' in address_lower:
        return "Residential Farm House"
    elif 'villa' in address_lower:
        return "Villa"
    elif 'office' in address_lower:
        return "Commercial Office Space"
    elif 'shop' in address_lower or 'Shop' in address_lower:
        return "Commercial Shop/Retail Space"
    elif 'warehouse' in address_lower:
        return "Warehouse"
    elif 'showroom' in address_lower:
        return "Commercial Showroom"
    elif 'land' in address_lower or 'vacant land' in address_lower:
        return "Land and Building" 
    
    
    # Default to Residential Plot 
    return "Residential Plot"



def generate_seo(property_title):

    prompt_template = (
                f"Create meta title, meta description, and h1 for the exact property title provided, without modifying, adding to, "
                f"or removing from the original title. The output must be a valid JSON object with only the following keys: ”meta_title”, "
                f"”meta_description”, and ”h1”. Do not include any explanations or extra text outside the JSON. The H1 must start with "
                f"“Buy” or contain “for sale” in the middle — randomly select one option per request. Meta title must follow the same rule: "
                f"either start with “Buy” or contain “for sale” in the middle — randomly select one. Meta title must be under 60 characters "
                f"and include a call to action like “Call Now”, “Best Price”, or “Bank Auction Property” if it is under 50 characters. "
                f"Meta description must be between 150–160 characters, use target keywords naturally, and include a strong call to action "
                f"and urgency, such as “Call now to schedule a visit.” Use clear, simple, and structured language following a subject-verb-object order. "
                f"Avoid filler, complex terms, or assumptions. Example H1: ”Buy 3 BHK Flat in Z Estates Z1, Patia, Bhubaneswar”. "
                f"Example Meta Title: ”3 BHK Apartment for sale in Patia – Call Now”. Example Meta Description: ”Buy a spacious 3 BHK flat in Patia "
                f"with modern amenities and great connectivity. Limited stock available. Call now to book a visit.” Follow all rules strictly "
                f"and output ONLY the JSON in key-pair format."
                f"{property_title}"
            )

    try:
        response = model.generate_content(prompt_template,
            safety_settings={
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH, 
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH
            })
        return response.text
        
    except Exception as e:
        log("INFO", f"Unable to generate seo - {e}")





def seo_tags(property_title):
    
    prompt_template = (
        f"## Real Estate SEO Content Generator (Strict Instructions)\n\n"
        f"This approach ensures that content ranks well, resonates with readers, and is accessible to both humans and search engines.\n"
        f"You are an expert SEO content writer for real estate listings. Based ONLY on the provided property title below, generate the following:\n"
        f"- H1 (Headline)\n"
        f"- Meta Title\n"
        f"- Meta Description\n"
        f"### Output Rules:\n"
        f"1. Do NOT assume missing information. Only use the property title provided.\n"
        f"2. Write clearly and simply. Use subject-verb-object structure. Avoid filler, jargon, or complex phrasing.\n"
        f"3. Optimize all content for search engines (NLP-friendly) and user readability.\n"
        f"4. Do NOT add asterisks, markdown, or bullet points. Just provide clean text values.\n\n"
        f"### H1 Guidelines:\n"
        f"- Clearly mention the property type (e.g., flat, house, plot, shop, etc.) and location.\n"
        f"-Either use Buy or sale but use any one is must mandatory.\n"
        f"- Use 'Buy' in H1 **only if** the property title implies a purchase (e.g., 'Buy', 'Available to Buy').\n"
        f"- Use 'For Sale' in H1 **only if** the property title mentions 'for sale', 'available for sale', or 'sale'.\n"
        f"- Do not use both 'Buy' and 'For Sale'. Choose based on the property title language.\n"
        f"- Append '– Bank Auction Property' at the end ONLY if the city is one of: Mumbai, Pune, New Delhi, Gurugram, Ghaziabad, Hyderabad, Bengaluru, Bengalore, Chennai, Noida, Goa.\n\n"
        f"### Meta Title Guidelines:\n"
        f"- Must match the property context (Buy or For Sale).\n"
        f"-Either use Buy or sale but use any one is must mandatory.\n"
        f"- Limit to 60 characters.\n"
        f"- Use keywords naturally (e.g., buy plot in Chennai).\n"
        f"- If under 50 characters, append a CTA like 'Best Price' or 'Call Now for a Visit'.\n"
        f"- Append '– Bank Auction Property' at the end ONLY if the city is one of the above.\n\n"
        f"### Meta Description Guidelines:\n"
        f"- Use 'Buy' or 'For Sale' in line with the property title.\n"
        f"- Either use Buy or sale but use any one is must mandatory.\n"
        f"- Limit to 150–160 characters.\n"
        f"- Be clear, simple, and informative. No exaggeration or assumptions.\n"
        f"- Use keywords naturally.\n"
        f"- Include a compelling CTA (e.g., 'Call now!', 'Visit today!').\n"
        f"- Highlight urgency or exclusivity if clear from the title.\n\n"
        f"### Property Title:\n"
        f"{property_title}\n"
    )
    
    while True:
        try:
            response = model.generate_content(prompt_template,
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_ONLY_HIGH, 
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_ONLY_HIGH,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_ONLY_HIGH
                })
              # Debugging the output
            
            #print(response.text)
            # Initialize variables
            h1, seo_keyword,seo_title, seo_description= "", "", "", ""
            lines = response.text.strip().split("\n")
            
            for line in lines:
                line = re.sub(r'\*\*\s*', '', line).strip()
                if "H1:" in line:
                    h1 = line.split(":",1)[-1].strip()
                    seo_keyword = h1
                elif "Meta Title:" in line:
                    seo_title = line.split(":",1)[-1].strip()
                elif "Meta Description:" in line:
                    seo_description = line.split(":",1)[-1].strip()
            #slug = h1.lower().replace(" ", "-").replace(",", "").replace("/", "-")
            #this have two version one for draft , one for bank
            
            
            return h1, seo_keyword, seo_title, seo_description
        
        except Exception as e:
            print(f"An error occurred: {e}")
            time.sleep(5)




    




# def extract_clean_address(cleaned_address):
#     """
#     Function to clean and condense the address into the desired format:
#     - Removes 'Site No.', 'Flat No.', floor information, and numeric details.
#     - Retains only building name, locality, area, and city.
#     """
#     # Remove patterns like 'Site No.', 'Flat No.', 'Floor', and other unnecessary info
#     address = re.sub(r'(Site No\.?|Flat No\.?|Door No\.?|Sy No\.?|Survey No\.?|Katha No\.?|Plot No\.?|Unit No\.?)\s*\w+[-\s\w]*,?', '', cleaned_address, flags=re.IGNORECASE)
#     address = re.sub(r'(\b\d+\s*(st|nd|rd|th)?\s*Floor\b)', '', cleaned_address, flags=re.IGNORECASE)  # Remove floor information
#     address = re.sub(r'\b\d+\b', '', cleaned_address)  # Remove standalone numbers
#     address = re.sub(r'\s*,\s*', ', ', cleaned_address.strip())  # Normalize commas and spaces
    
#     # Retain building name, area/locality, and city
#     return cleaned_address.strip()



def generate_property_title(property_type_ind, cleaned_address,super_clean_address):
    """
    Function to generate the property title with proper area structure.
    """
    # Initialize variables
    locality = "Unknown Area"
    city = "Unknown City"
    buildingname = "Unknown Area"
    area_1 = "Unknown Area 1"
    area_2 = "Unknown Area 2"

    parts = cleaned_address.split(',')

    if len(parts) >= 3:
        area_1 = parts[-3].strip()
        area_2 = parts[-2].strip()
        city = parts[-1].strip()

        # Check for building name for flat properties
        if property_type_ind == "Residential Flat" and len(parts) > 2:
            buildingname = parts[2].strip()

    # Handle city name correction if needed
    if city.lower() == "delhi":
        city = "New Delhi"
        
    for part in parts:
        part = part.strip()
        if any(keyword in part.lower() for keyword in ["apartment", "complex", "residency"]):
            buildingname = part
            break
            
    if buildingname == area_1:
        buildingname = ""
        
    # Construct property title
    if property_type_ind == "Residential Flat":
        title_parts = [buildingname, area_1, area_2, city]
        title_parts = [part for part in title_parts if part]
        super_clean_address = re.sub(r'\b(?:Village|Vilage|Taluk|Taluka|gaon|gram)\b\s*', '', super_clean_address, flags=re.IGNORECASE)
        super_clean_address = re.sub(r'\s*,\s*', ', ', super_clean_address).strip()
        return f"{property_type_ind} in {super_clean_address}"
    
    if property_type_ind == "Residential House/Building":
         super_clean_address = re.sub(r'\b(?:Village|Vilage|Taluk|Taluka|gaon|gram)\b\s*', '', super_clean_address, flags=re.IGNORECASE)
         super_clean_address = re.sub(r'\s*,\s*', ', ', super_clean_address).strip()
         return f"Independent House in {super_clean_address}"
    
    if property_type_ind == "Commercial Shop/Retail Space":
         super_clean_address = re.sub(r'\b(?:Village|Vilage|Taluk|Taluka|gaon|gram)\b\s*', '', super_clean_address, flags=re.IGNORECASE)
         super_clean_address = re.sub(r'\s*,\s*', ', ', super_clean_address).strip()
         return f"Commercial Shop in {super_clean_address}"

    # For any other property type, ensure it includes 3 areas
    super_clean_address = re.sub(r'\b(?:Village|Vilage|Taluk|Taluka|gaon|gram)\b\s*', '', super_clean_address, flags=re.IGNORECASE)
    super_clean_address = re.sub(r'\s*,\s*', ', ', super_clean_address).strip()

    return f"{property_type_ind} in {super_clean_address}"

marathi_to_english_state = {
    "महाराष्ट्र": "Maharashtra",
    "उत्तर प्रदेश": "Uttar Pradesh",
    "मध्य प्रदेश": "Madhya Pradesh",
    "राजस्थान": "Rajasthan",
    "गुजरात": "Gujarat",
    "कर्नाटक": "Karnataka",
    "तमिळनाडू": "Tamil Nadu",
    "आंध्र प्रदेश": "Andhra Pradesh",
    "तेलंगणा": "Telangana",
    "पश्चिम बंगाल": "West Bengal",
    "बिहार": "Bihar",
    "झारखंड": "Jharkhand",
    "ओडिशा": "Odisha",
    "छत्तीसगढ": "Chhattisgarh",
    "उत्तराखंड": "Uttarakhand",
    "हिमाचल प्रदेश": "Himachal Pradesh",
    "पंजाब": "Punjab",
    "हरियाणा": "Haryana",
    "गोवा": "Goa",
    "त्रिपुरा": "Tripura",
    "मणिपूर": "Manipur",
    "मेघालय": "Meghalaya",
    "नागालँड": "Nagaland",
    "मिझोराम": "Mizoram",
    "सिक्कीम": "Sikkim",
    "अरुणाचल प्रदेश": "Arunachal Pradesh",
    "असम": "Assam",
    "केरळ": "Kerala",
    "दिल्ली": "Delhi"
}
marathi_to_english_city = {
    "कोण":"kon",
    "मुंबई": "Mumbai",
    "पुणे": "Pune",
    "ठाणे": "Thane",
    "नाशिक": "Nashik",
    "नागपूर": "Nagpur",
    "औरंगाबाद": "Aurangabad",
    "सोलापूर": "Solapur",
    "सांगली": "Sangli",
    "कोल्हापूर": "Kolhapur",
    "अमरावती": "Amravati",
    "जळगाव": "Jalgaon",
    "अहमदनगर": "Ahmednagar",
    "रत्नागिरी": "Ratnagiri",
    "सातारा": "Satara",
    "बीड": "Beed",
    "लातूर": "Latur",
    "परभणी": "Parbhani",
    "उस्मानाबाद": "Osmanabad",
    "धुळे": "Dhule",
    "हिंगोली": "Hingoli",
    "नंदुरबार": "Nandurbar",
    "गडचिरोली": "Gadchiroli",
    "भंडारा": "Bhandara",
    "चंद्रपूर": "Chandrapur",
    "गोंदिया": "Gondia",
    "पालघर": "Palghar",
    "वाशीम": "Washim",
    "यवतमाळ": "Yavatmal",
    "बुलढाणा": "Buldhana",
    "जालना": "Jalna",
    "धुळे": "Dhule",
    "बोरिवली": "Borivali",
    "विरार": "Virar",
    "पनवेल": "Panvel",
    "दादर": "Dadar",
    "वडाळा": "Wadala",
    "घाटकोपर": "Ghatkopar"
}


def get_location_details(super_clean_address):
    """
    unction to get geolocation details using the Google Maps API.
    """
    try:
      geocode_result = gmaps.geocode(super_clean_address,language='en',region='in')
    except Exception as e:
        log("ERROR",f"An error occurred in get_location_details: {e}")
        return (None, None, None, None, 0.0, 0.0)
   
    if geocode_result:
        location = geocode_result[0]['geometry']['location']
        address_components = geocode_result[0]['address_components']
        
        latitude = location['lat']
        longitude = location['lng']
        
        postal_code = city = state = None

        
        
        # Loop through the address components to extract relevant details
        for component in address_components:
            if 'postal_code' in component['types']:
                postal_code = component['long_name']
            if 'locality' in component['types']:
                city = component['long_name']
            if 'administrative_area_level_1' in component['types']:
                state = component['long_name']
                
        state = marathi_to_english_state.get(state, state)
        city  = marathi_to_english_city.get(city,city)
       
        if city == "Delhi":
            city = "New Delhi"
            state = "Delhi"
            
        
        # If postal_code is not found, attempt reverse geocoding using lat/lng
        if not postal_code:
            reverse_geocode_result = gmaps.reverse_geocode((latitude, longitude), language='en')
            if reverse_geocode_result:
                for component in reverse_geocode_result[0]['address_components']:
                    if 'postal_code' in component['types']:
                        postal_code = component['long_name']
                    if 'locality' in component['types']:
                        city = component['long_name']
                    if 'administrative_area_level_1' in component['types']:
                        state = component['long_name']
        
            state = marathi_to_english_state.get(state, state)
            city  = marathi_to_english_city.get(city,city)
            
        if not city:
            parts = super_clean_address.strip().split()
            if len(parts) >= 2 and parts[-1].lower() == parts[-2].lower():
                city = parts[-1].title()
            elif parts:
                city = parts[-1].title()

        # **Constraint: Check if latitude and longitude are within India's range**
        if 6.5546 <= latitude <= 35.6745 and 68.1113 <= longitude <= 97.3956:
            log("INFO", f"New lat - {latitude}, lng - {longitude}")
            return (super_clean_address, city, state, postal_code, latitude, longitude)
        
        else:
            log("INFO","Location is outside India's boundaries.")
            return (None, None, None, None, 0.0, 0.0)

    else:
        log("INFO","Exact address not found. Providing approximate coordinates.")
        return (None, None, None, None, 0.0, 0.0)
     
# Load India's detailed land boundary (without sea or EEZ)
def is_it_india_lat_lng(longitude, latitude):
    india = gpd.read_file(config.get_key('GEOJSON_FILE'))
    point = Point(longitude, latitude)  # (lon, lat)
    is_in_india = india.contains(point).any()
    return is_in_india  # It will return True or False

def get_street_view_link(property_type,latitude, longitude):
    """
    Function to generate a Google Street View iframe using latitude and longitude.
    """
    # Base URL for Google Street View embed
    
    
    
    base_url = "https://www.google.com/maps/embed/v1/streetview" 
    
    global MAPS_API_KEY
    api_key= MAPS_API_KEY

    # Construct the Street View iframe URL
    iframe_url = f"{base_url}?key={api_key}&location={latitude},{longitude}&heading=0&pitch=0&fov=90"

    #If you want to give street view to all , then remove condition , and property tupe argument in function and when we pass  , remvome it from display data ,function     
    # Return the iframe code
    if property_type in ["Residential Flat", "Commercial Shop/Retail Space"]:
        iframe_code = (
        f'<iframe src="{iframe_url}" width="400" height="300" style="border:0;" '
        f'allowfullscreen="" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>'
        )
        return iframe_code
    else:
        return None



def haversine(lat1, lon1, lat2, lon2):
    """Calculate the distance between two points on the Earth's surface."""
    R = 6371  # Radius of the Earth in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def find_main_amenities(lat, lon, api_key, property_type):
    """
    Find main amenities: CBSE schools, hospitals, malls, D-Mart.
    Adjust output format based on property type.
    """
    amenities = []
    formatted_amenities = []
    
    # CBSE Schools
    response = requests.get(f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=school&key={api_key}")
    results = response.json().get('results', [])
    if results:
        place = results[0]
        distance = haversine(lat, lon, place['geometry']['location']['lat'], place['geometry']['location']['lng'])
        amenities.append((distance, place['name'], "CBSE School"))

    # Hospitals
    response = requests.get(f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=hospital&key={api_key}")
    results = response.json().get('results', [])
    if results:
        place = results[0]
        distance = haversine(lat, lon, place['geometry']['location']['lat'], place['geometry']['location']['lng'])
        amenities.append((distance, place['name'], "Hospital"))

    # Shopping Malls
    response = requests.get(f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&type=shopping_mall&key={api_key}")
    results = response.json().get('results', [])
    if results:
        place = results[0]
        distance = haversine(lat, lon, place['geometry']['location']['lat'], place['geometry']['location']['lng'])
        amenities.append((distance, place['name'], "Mall"))

    #Supermark Stores
    response = requests.get(f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=5000&keyword=supermarket&key={api_key}")
    results = response.json().get('results', [])
    if results:
        place = results[0]
        distance = haversine(lat, lon, place['geometry']['location']['lat'], place['geometry']['location']['lng'])
        amenities.append((distance, place['name'], "Supermarket"))

    # Sort amenities by distance in ascending order
    amenities.sort(key=lambda x: x[0])

    # Format amenities based on property type
    if property_type == "Residential Flat":
        # Include distance for Residential Flats
        formatted_amenities = [f"{round(amenity[0], 1)} km to {amenity[1]} ({amenity[2]})" for amenity in amenities]
    else:
        # Use generic phrases for Residential Plot or Residential House/Building
        generic_phrases = ["Close to", "Near by"]
        for i, amenity in enumerate(amenities[:4]):  # Limit to top 4 amenities
            phrase = generic_phrases[i % len(generic_phrases)]  # Rotate phrases
            formatted_amenities.append(f"{phrase} {amenity[1]} ({amenity[2]})")

    return " | ".join(formatted_amenities)


def append_to_excel(data, filename="F:\\Hecta\\Bulkoriginalazhar.xlsx"):
    """
    Function to append data to an Excel file.
    """
    try:
        existing_data = pd.read_excel(filename, engine='openpyxl')
    except FileNotFoundError:
        existing_data = pd.DataFrame(columns=['Address', 'Property Type', 'Property Title', 'City', 'State', 'Pincode', 'Latitude', 'Longitude', 'Location Type', 'Street View', 'Amenities','Primary Photo','Locality','SEO Keyword','SEO Title','SEO Description','area'])
    new_data = pd.DataFrame(data, columns=['Address', 'Property Type', 'Property Title', 'City', 'State', 'Pincode', 'Latitude', 'Longitude', 'Location Type', 'Street View', 'Amenities','Primary Photo','Locality','SEO Keyword','SEO Title','SEO Description','area'])
    
    updated_data = pd.concat([existing_data, new_data], ignore_index=True)
    updated_data.to_excel(filename, index=False, engine='openpyxl')


def find_famous_amenities(lat, lon, api_key):
    """Find famous amenities: metro stations, railway stations, bus stands, colleges, hotels, restaurants, IT parks, and other places."""
    famous_amenities = defaultdict(list)
    types = [
        ("subway_station", "Metro Station"),  # Metro stations
        ("train_station", "Railway Station"), # Railway stations
        ("bus_station", "Bus Stand"),         # Bus stands
        ("university", "College"),            # Colleges
        ("hotel", "Hotel"),                   # Hotels
        ("restaurant", "Restaurant"),         # Restaurants
        ("park", "IT/Knowledge Park"),        # IT Parks / Knowledge Parks
        ("stadium", "Other Points of Interest"), # Stadiums & Others (catch-all)
        ("point_of_interest", "Other Points of Interest")  # General points of interest
    ]
    
    # Search for each type within a 7 km radius
    for place_type, display_name in types:
        response = requests.get(f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?location={lat},{lon}&radius=7000&type={place_type}&key={api_key}")
        results = response.json().get('results', [])
        
        for place in results:
            # Calculate distance of the place from the user's coordinates
            distance = haversine(lat, lon, place['geometry']['location']['lat'], place['geometry']['location']['lng'])
            
            # Only include places that are within 7 km
            if distance <= 7:
                famous_amenities[display_name].append((distance, place['name'], place_type))

    # Sort amenities within each category by distance
    for category in famous_amenities:
        famous_amenities[category].sort(key=lambda x: x[0])

    return famous_amenities

def display_table(data):
    """
    Function to display the result in a tabular format.
    """
    df = pd.DataFrame(data, columns=['Address', 'Property Type', 'Property Title', 'City', 'State', 'Pincode', 'Latitude', 'Longitude', 'Location Type', 'Street View', 'Amenities','Primary Photo','Locality','SEO Keyword','SEO Title','SEO Description','area'])
    for index, row in df.iterrows():
        print(f"\nRecord {index + 1}:")
        print(f"  Address        : {row['Address']}")
        print(f"  Property Type  : {row['Property Type']}")
        print(f"  Property Title : {row['Property Title']}")
        print(f"  City           : {row['City']}")
        print(f"  State          : {row['State']}")
        print(f"  Pincode        : {row['Pincode']}")
        print(f"  Latitude       : {row['Latitude']}")
        print(f"  Longitude      : {row['Longitude']}")
        print(f"  Location Type  : {row['Location Type']}")
        print(f"  Street View    : {row['Street View']}")
        print(f"  Amenities      : {row['Amenities']}")
        print(f"  Primary Photo  : {row['Primary Photo']}")
        print(f"  Locality       : {row['Locality']}")
        print(f"  SEO Keyword    : {row['SEO Keyword']}")
        print(f"  SEO Title      : {row['SEO Title']}")
        print(f"  SEO Description: {row['SEO Description']}")
        print(f"  Area           : {row['area']}")
        
        

def determine_location_type(property_type):
    """
    Function to determine the location type based on the property type.
    """
    # Fix: Residential Flat should always have location type as 'Exact'
    if property_type == "Residential Flat":
        return "Exact"
    elif property_type == "Residential Plot" or property_type == "Residential House/Building":
        return "Approx"
    else:
        return "Approx"

def determine_primary_photo(property_type, cleaned_address):
    """
    Function to determine the primary photo URL based on property type and cleaned address.
    """
    if property_type == "Residential Plot":
        return "https://hecta-website.s3.ap-south-1.amazonaws.com/2024/11/media/1731674068_975fb743e5dd31cd.jpg"
    elif property_type == "Residential House/Building" or "row house" in cleaned_address.lower():
        return "https://hecta-website.s3.ap-south-1.amazonaws.com/2024/11/media/1731734069_8b0b8742bf274c7f.jpg"
    elif property_type == "Land and Building":
        return "https://hecta-website.s3.ap-south-1.amazonaws.com/2024/11/media/1731741519_9dc0a56cc67c56ec.jpg"
    elif property_type == "Residential Builder Floor": 
        return "https://hecta-website.s3.ap-south-1.amazonaws.com/2024/12/media/1735536562_b6c993d1c1a18a8b.jpg"
    elif property_type == "Commercial Shop/Retail Space":
        return "https://hecta-website.s3.ap-south-1.amazonaws.com/2025/01/media/1736247989_3e36aed48fc77a4d.jpg"
    else:
        return None  

import googlemaps

#For locality
# Function to initialize Google Maps API
def initialize_gmaps(api_key):
    return googlemaps.Client(key=api_key)

# Function to check sub-locality using Reverse Geocoding
def get_sublocality(gmaps, latitude, longitude):
    reverse_geocode_result = gmaps.reverse_geocode((latitude, longitude))
    for result in reverse_geocode_result:
        for component in result['address_components']:
            if 'sublocality' in component['types']:
                return component['long_name']
    return None  # If no sub-locality found

# Function to search for nearby places (school, hospital, railway station)
def search_nearby_places(gmaps,latitude, longitude,radius=7000):
    places = {
        "school": [],
        "hospital": [],
        "railway_station": []
    }

    # Search for schools
    school_results = gmaps.places_nearby((latitude, longitude), radius=radius, type="school")
    if school_results.get('results'):
        places["school"] = school_results['results']

    # Search for hospitals
    hospital_results = gmaps.places_nearby((latitude, longitude), radius=radius, type="hospital")
    if hospital_results.get('results'):
        places["hospital"] = hospital_results['results']

    # Search for railway stations
    railway_results = gmaps.places_nearby((latitude, longitude), radius=radius, type="train_station")
    if railway_results.get('results'):
        places["railway_station"] = railway_results['results']
    
    #return places










# Main Functionality

def get_catalog(property_json):
    
    if 'property_description' not in property_json or property_json['property_description'] is None:
        property_json["should_process"]=False
        return None
    
    address=property_json['property_description']
    
    i=1
    enriched_property={}
    for i in range(1,2):
        i+=1    
        # Step 1: Clean the address
        cleaned_address, Area, MicroMarket, buildingname, super_clean_address, property_type_ind = clean_address(address)
        super_cleaned_address = super_clean_address.replace("\n"," ")

        

        h1, seo_keyword, seo_title, seo_description = seo_tags(cleaned_address)

        
        # Step 2: Get location details (city, state, pincode, latitude, longitude)
        details = get_location_details(super_cleaned_address)
        if details is None:
            property_json["should_process"]=False
            return 
        city = details[1]
        state = details[2]
        postal_code = details[3]

        if 'latitude' not in property_json or 'longitude' not in property_json or property_json['latitude'] is None or property_json['longitude'] is None:
            latitude = details[4]
            longitude = details[5]
        else :
            latitude = property_json['latitude']
            longitude = property_json['longitude']
        
        # Step 3: Determine property type and title
        property_type = determine_property_type(cleaned_address)
        property_title = generate_property_title(property_type_ind, cleaned_address, super_clean_address)
        property_title = property_title.replace("\n"," ")

        # Determine location type based on property type
        location_type = determine_location_type(property_type_ind)

        # Step 4: Get main amenities
        #main_amenities = find_main_amenities(latitude, longitude, api_key,property_type)
        #amenities_list = [f"{distance:.1f} km to {name} ({amenity_type})" for distance, name, amenity_type in main_amenities]

        #step4: 
        #street_view_cleaned_address = extract_clean_address(cleaned_address)
        
        # Step 5: Get famous amenities (within 7 km)
        #famous_amenities = find_famous_amenities(latitude, longitude, api_key)

        # Step 5: Determine primary photo based on property type and cleaned address
        primary_photo = determine_primary_photo(property_type, cleaned_address)

        #STep 8: Locality
        locality = get_sublocality(gmaps, latitude, longitude)
        
        # Step 6: Prepare the data to display
        enriched_property['cleaned_address']=cleaned_address
        enriched_property['property_type']=property_type
        enriched_property['property_title']=property_title
        enriched_property['city']=city
        enriched_property['state']=state
        enriched_property['postal_code']=postal_code
        enriched_property['latitude']=latitude
        enriched_property['longitude']=longitude
        enriched_property['location_type']=location_type
        enriched_property['streetview_url']=get_street_view_link(property_type,latitude, longitude)
        enriched_property['main_amenities']=""
        enriched_property['locality']=locality
        enriched_property['seo_keyword']=seo_keyword.lower()
        enriched_property['seo_title']=seo_title.lower()
        enriched_property['seo_description']=seo_description.lower()
        enriched_property['Area']=Area
        property_json['enriched_property']=enriched_property
        property_json["should_process"]=True

        return enriched_property
       
#json_str='[{"notice_image": "", "contact_officer": "SANTOSH KHAVARE", "contact_office_number": "9819906655", "emd": 0, "emd_payment_mode": "", "property_description": "Gut No: 169/Cts No. 1627/54, Building Name: Golden Isle Chsl, House No: A/405, Floor No: 4Th, Plot No: 169/Cts No. 1627/54, Land Mark: Nr. Majur Nagar, Village: Maroshi, Location: Goregaon East, Taluka: Borivali, State: Maharashtra, Pin Code: 400063, Police Station: Goregaon East, North By: Palm 1/2/3 Chsl, South By: Internal Road, East By: Inor Hotel, West By: Road / Built-up Area 266 SQ Ft.", "application_end_date_time": "2025-06-28T17:00:00", "auction_date_time": "2025-06-30T15:00:00", "visit_date": "", "borrower_name": "MALAY SUDHINDRAKUMAR GARG", "reserve_price": 2427345, "total_dues": 6730237, "possession_type": "physical", "notice_type": "Auction Notice", "bank": "GIC Housing Finance Ltd"}]'
#property_json_list=json.loads(json_str)
#for property_json in property_json_list:
#    property_json['enriched_property']=get_catalog(property_json)
#    print(json.dumps(property_json))
    #insert_data(property_json) 
